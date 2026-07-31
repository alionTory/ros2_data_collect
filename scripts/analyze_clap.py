"""박수 시험 — 영상과 오디오의 이벤트 시각 차이로 동기화 오차를 측정한다.

박수 한 번이 두 스트림 모두에 뚜렷한 이벤트를 남긴다.

    영상   손이 맞닿는 순간   연속 프레임 차분의 최대점
    오디오 파열음             단시간 에너지의 급상승 지점

두 이벤트의 시각 차이가 곧 동기화 오차다. 비교 대상은 각 메시지의 header.stamp이며,
bag의 수신 시각이 아니다. 후자는 발행 지연을 포함하므로 측정하려는 값이 아니다.

사용법
    source ~/ros2_data_collect/install/setup.bash
    python3 scripts/analyze_clap.py sessions/2026-07-31_093012_clap

의존성은 numpy와 JPEG 디코더(cv2 또는 PIL) 하나다. 둘 다 apt로 설치한다.
    sudo apt install python3-opencv     # 또는 python3-pil
"""
import argparse
import csv
import statistics
import sys

import numpy as np

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

VIDEO_TOPIC = '/sensors/camera/image_raw/compressed'
AUDIO_TOPIC = '/sensors/audio/chunk'

# 오디오 단시간 에너지 계산 창. 128샘플 = 8ms로, 영상 분해능 33ms보다 충분히 촘촘하다.
AUDIO_WINDOW = 128
AUDIO_HOP = 64

# 영상 차분 계산 시 축소 크기. 박수는 큰 움직임이라 이 해상도로 충분하고 디코딩이 빨라진다.
VIDEO_SCALE = 4


# --- JPEG 디코딩 -----------------------------------------------------------

def _make_decoder():
    """cv2 또는 PIL 중 사용 가능한 것으로 그레이스케일 디코더를 만든다."""
    try:
        import cv2

        def decode(jpeg_bytes):
            buffer = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            image = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
            if image is None:
                return None
            return image[::VIDEO_SCALE, ::VIDEO_SCALE].astype(np.int16)

        return decode
    except ImportError:
        pass

    try:
        import io
        from PIL import Image

        def decode(jpeg_bytes):
            image = Image.open(io.BytesIO(jpeg_bytes)).convert('L')
            array = np.asarray(image)
            return array[::VIDEO_SCALE, ::VIDEO_SCALE].astype(np.int16)

        return decode
    except ImportError:
        sys.exit('JPEG 디코더가 없습니다. sudo apt install python3-opencv 또는 python3-pil')


# --- bag 읽기 --------------------------------------------------------------

def read_bag(path: str, storage_id: str):
    """bag을 한 번 훑어 영상·오디오 메시지를 시각과 함께 모은다."""
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=path, storage_id=storage_id),
        rosbag2_py.ConverterOptions('', ''),
    )
    type_map = {t.name: t.type for t in reader.get_all_topics_and_types()}

    for topic in (VIDEO_TOPIC, AUDIO_TOPIC):
        if topic not in type_map:
            sys.exit(f'bag에 {topic}이 없습니다. 기록된 토픽: {sorted(type_map)}')

    videos, audios = [], []
    while reader.has_next():
        topic, payload, _recv_ns = reader.read_next()
        if topic not in (VIDEO_TOPIC, AUDIO_TOPIC):
            continue
        message = deserialize_message(payload, get_message(type_map[topic]))
        stamp_ns = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        if topic == VIDEO_TOPIC:
            videos.append((stamp_ns, bytes(message.data)))
        else:
            audios.append((stamp_ns, message))

    # 기록 순서가 시각 순서와 다를 수 있다.
    videos.sort(key=lambda item: item[0])
    audios.sort(key=lambda item: item[0])
    return videos, audios


# --- 특징량 추출 -----------------------------------------------------------

def video_motion(videos, decode):
    """연속 프레임 차분. 반환은 (시각[초], 차분값) 두 배열."""
    times, values = [], []
    previous = None
    invalid = 0
    for stamp_ns, jpeg in videos:
        frame = decode(jpeg)
        if frame is None:
            invalid += 1
            continue
        if previous is not None:
            # 차분은 두 프레임 사이의 사건이므로 뒤 프레임의 시각을 쓴다.
            times.append(stamp_ns / 1e9)
            values.append(float(np.abs(frame - previous).mean()))
        previous = frame
    if invalid:
        print(f'  [!] 디코딩 실패 프레임 {invalid}개')
    return np.array(times), np.array(values)


def audio_energy(audios):
    """단시간 RMS. 청크 첫 샘플 시각에 청크 내 위치를 더해 시각을 구한다."""
    times, values = [], []
    for stamp_ns, message in audios:
        samples = np.asarray(message.data, dtype=np.int16).astype(np.float32)
        if message.channels > 1:
            samples = samples.reshape(-1, message.channels).mean(axis=1)
        start_sec = stamp_ns / 1e9
        for offset in range(0, len(samples) - AUDIO_WINDOW + 1, AUDIO_HOP):
            window = samples[offset:offset + AUDIO_WINDOW]
            times.append(start_sec + offset / message.sample_rate)
            values.append(float(np.sqrt(np.mean(window * window))))
    return np.array(times), np.array(values)


# --- 이벤트 검출 -----------------------------------------------------------

def find_events(times, values, threshold_ratio, refractory_sec):
    """기준선 위로 크게 솟은 구간마다 최대점 하나를 이벤트로 고른다.

    기준선은 중앙값을 쓴다. 평균은 박수 자체에 끌려 올라가 문턱이 높아진다.
    """
    if len(values) == 0:
        return []
    baseline = float(np.median(values))
    peak = float(values.max())
    if peak <= baseline:
        return []
    threshold = baseline + threshold_ratio * (peak - baseline)

    above = np.flatnonzero(values >= threshold)
    if len(above) == 0:
        return []

    events = []
    group = [above[0]]
    for index in above[1:]:
        # 같은 박수의 잔향이 끊겼다 이어져도 하나로 묶는다.
        if times[index] - times[group[-1]] <= refractory_sec:
            group.append(index)
        else:
            events.append(group)
            group = [index]
    events.append(group)

    return [float(times[max(group, key=lambda i: values[i])]) for group in events]


def pair_events(video_events, audio_events, max_gap_sec):
    """영상 이벤트마다 가장 가까운 오디오 이벤트를 찾는다.

    개수가 달라도 동작하도록 순서 짝짓기 대신 최근접으로 붙인다.
    """
    pairs = []
    for video_time in video_events:
        if not audio_events:
            break
        nearest = min(audio_events, key=lambda audio_time: abs(video_time - audio_time))
        if abs(video_time - nearest) <= max_gap_sec:
            pairs.append((video_time, nearest, video_time - nearest))
    return pairs


# --- 보고 -----------------------------------------------------------------

def report(pairs, video_events, audio_events, video_interval_sec, output_csv):
    print(f'\n검출: 영상 {len(video_events)}회, 오디오 {len(audio_events)}회, '
          f'짝 지어진 것 {len(pairs)}회')

    if len(pairs) < 2:
        sys.exit('짝이 2개 미만입니다. --threshold를 낮추거나 --max-gap을 늘려 보세요.')

    deltas_ms = [delta * 1000 for _, _, delta in pairs]
    mean = statistics.mean(deltas_ms)
    stdev = statistics.stdev(deltas_ms)
    resolution_ms = video_interval_sec * 1000 / 2

    print('\n=== 동기화 정확도 ===')
    print(f'평균 오차   {mean:+.1f} ms   (양수 = 영상이 오디오보다 늦음)')
    print(f'표준편차     {stdev:.1f} ms')
    print(f'범위        {min(deltas_ms):+.1f} ~ {max(deltas_ms):+.1f} ms')
    print(f'표본 수      {len(deltas_ms)}')
    print(f'영상 분해능  ±{resolution_ms:.0f} ms (프레임 간격 {video_interval_sec * 1000:.1f}ms의 절반)')

    print('\n평균은 계통 편향, 표준편차는 재현성을 나타낸다.')
    print('영상 이벤트는 손이 맞닿기 직전(움직임이 가장 빠른 순간)에 검출되므로')
    print('평균에는 1프레임 수준의 고정 편향이 섞인다. 표준편차가 더 신뢰할 만하다.')

    with open(output_csv, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['video_time_sec', 'audio_time_sec', 'delta_ms'])
        for video_time, audio_time, delta in pairs:
            writer.writerow([f'{video_time:.6f}', f'{audio_time:.6f}', f'{delta * 1000:.2f}'])
    print(f'\n원자료: {output_csv}')


def main():
    parser = argparse.ArgumentParser(description='박수 시험 분석')
    parser.add_argument('bag', help='bag 디렉터리 경로')
    parser.add_argument('--storage', default='sqlite3', help='sqlite3 또는 mcap')
    parser.add_argument('--threshold', type=float, default=0.35,
                        help='기준선 위 최대치의 몇 배부터 이벤트로 볼지 (0~1)')
    parser.add_argument('--refractory', type=float, default=1.0,
                        help='한 박수로 묶을 시간 범위(초)')
    parser.add_argument('--max-gap', type=float, default=0.3,
                        help='영상·오디오 이벤트를 짝지을 최대 시간차(초)')
    parser.add_argument('--csv', default='sync_accuracy.csv')
    arguments = parser.parse_args()

    print(f'bag 읽는 중: {arguments.bag}')
    videos, audios = read_bag(arguments.bag, arguments.storage)
    print(f'  영상 {len(videos)}개, 오디오 {len(audios)}개')

    if len(videos) < 2 or len(audios) < 2:
        sys.exit('메시지가 너무 적습니다.')

    # 소스별 구간으로 실측 주기를 구한다. 전역 경과 시간으로 나누면
    # 늦게 시작한 소스가 과대평가된다.
    video_span = (videos[-1][0] - videos[0][0]) / 1e9
    audio_span = (audios[-1][0] - audios[0][0]) / 1e9
    video_interval = video_span / (len(videos) - 1)
    print(f'  영상 {(len(videos) - 1) / video_span:.2f}Hz (구간 {video_span:.1f}초), '
          f'오디오 {(len(audios) - 1) / audio_span:.2f}Hz (구간 {audio_span:.1f}초)')

    overlap = min(videos[-1][0], audios[-1][0]) - max(videos[0][0], audios[0][0])
    print(f'  겹침 구간 {overlap / 1e9:.1f}초  ← 짝을 만들 수 있는 범위')

    decode = _make_decoder()
    print('특징량 추출 중...')
    video_times, video_values = video_motion(videos, decode)
    audio_times, audio_values = audio_energy(audios)

    video_events = find_events(video_times, video_values,
                               arguments.threshold, arguments.refractory)
    audio_events = find_events(audio_times, audio_values,
                               arguments.threshold, arguments.refractory)

    pairs = pair_events(video_events, audio_events, arguments.max_gap)
    report(pairs, video_events, audio_events, video_interval, arguments.csv)


if __name__ == '__main__':
    main()