"""
오디오 데이터 캡처 후 바로 전송하려 하면, 네트워크가 밀리면서 샘플이 유실될 수 있음.
캡처 후 queue에 데이터를 넣은 뒤, 네트워크에서 큐에서 꺼낸 값을 전송할 것.
"""
import time
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'data_collect'))
from data_collect import protocol
import socket
import cv2
import queue
import threading
import sounddevice as sd

class AtomicCounter:
    def __init__(self, initial_value):
        self._lock = threading.Lock()
        self._value = initial_value
    
    def increase(self):
        with self._lock:
            self._value += 1
    
    def decrease(self):
        with self._lock:
            self._value -= 1

    @property
    def value(self):
        return self._value

class FrameSender:
    QUEUE_MAX = 400
    VIDEO_IN_QUEUE_MAX = 60
    """
    큐 안에 존재할 수 있는 비디오 데이터 개수의 상한.
    
    큐가 비디오로 가득 차서 오디오가 유실되는 것을 막기 위한 용도.
    """
    
    def __init__(self):
        self.queue: queue.Queue[tuple[int, int, int, bytes]] = queue.Queue(maxsize=FrameSender.QUEUE_MAX)
        """
        (payload_type: int, timestamp_ns: int, seq: int, payload: bytes) 튜플을 저장하는 큐
        """

        self.send_success = {protocol.TYPE_VIDEO_JPEG: 0, protocol.TYPE_AUDIO_PCM: 0}
        self.send_error = None

        self.video_in_queue_count = AtomicCounter(0)
        self.video_overflow = 0

        self.audio_overflow = 0

        self.running = True
        
    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(('127.0.0.1', protocol.DEFAULT_PORT))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # TCP Nagle을 비활성화해 지연 감소.

        self.thread = threading.Thread(target=self._send_loop, daemon=True)
        self.thread.start()

        return self

    def __exit__(self, exc_type, exc, tb):
        self.running = False
        self.thread.join(timeout=2)
        self.sock.close()
    
    def send_success_count(self, payload_type):
        return self.send_success[payload_type]

    def put_video(self, timestamp_ns: int, seq: int, jpeg: bytes):
        """
        큐에 비디오 데이터를 넣어 나중에 전송할 수 있도록 한다.
        
        큐에 자리가 없으면 인수로 주어진 데이터를 버린다.
        """
        if self.video_in_queue_count.value >= FrameSender.VIDEO_IN_QUEUE_MAX:
            self.video_overflow += 1
        else:
            try:
                self.queue.put_nowait((protocol.TYPE_VIDEO_JPEG, timestamp_ns, seq, jpeg))
                self.video_in_queue_count.increase()
            except queue.Full:
                self.video_overflow += 1

    
    def put_audio(self, timestamp_ns: int, seq: int, payload: bytes):
        """
        큐에 오디오 데이터를 넣어 나중에 전송할 수 있도록 한다.
        
        큐에 자리가 없으면 인수로 주어진 데이터를 버린다.
        """
        try:
            self.queue.put_nowait((protocol.TYPE_AUDIO_PCM, timestamp_ns, seq, payload))
        except queue.Full:
            self.audio_overflow += 1
    
    def _send_loop(self):
        while self.running:
            try:
                payload_type, timestamp_ns, seq, payload = self.queue.get(timeout=0.2)
                if payload_type == protocol.TYPE_VIDEO_JPEG:
                    self.video_in_queue_count.decrease()
                try:
                    protocol.send_frame(self.sock, payload_type, timestamp_ns, seq, payload)
                    self.send_success[payload_type] += 1
                except OSError as e:
                    self.running = False
                    self.send_error = e
            except queue.Empty:
                pass
                
            

class VideoCapturer:
    MAX_CONSECUTIVE_CAPTURE_FAILURE = 30
    FRAME_WIDTH = 640
    FRAME_HEIGHT = 480
    def __init__(self, frame_sender: FrameSender):
        self.frame_sender = frame_sender
        self.next_seq = 0
        self.capture_fail_count = 0
        self.consecutive_capture_fail_count = 0
        self.running = True
    
    def __enter__(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            raise RuntimeError("카메라를 사용할 수 없습니다.")
        
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, VideoCapturer.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VideoCapturer.FRAME_HEIGHT)
        print(f"카메라 설정됨. 너비: {self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)}, 높이: {self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")

        self.thread = threading.Thread(target=self._start_capture, daemon=True)
        self.thread.start()

        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        self.thread.join(timeout=2)
        self.cap.release()
    
    def _start_capture(self):
        while self.running:
            capture_success, image_raw = self.cap.read()
            seq = self.next_seq
            self.next_seq += 1
            if capture_success:
                self._put_jpeg_to_frame_sender(image_raw, seq)
            else:
                self._process_capture_failure()
    
    def _process_capture_failure(self):
        self.capture_fail_count += 1
        self.consecutive_capture_fail_count += 1
        if VideoCapturer.MAX_CONSECUTIVE_CAPTURE_FAILURE <= self.consecutive_capture_fail_count:
            raise RuntimeError(f"카메라 프레임 캡처 {self.consecutive_capture_fail_count}번 연속 실패")
        time.sleep(0.01)

    def _put_jpeg_to_frame_sender(self, image_raw, seq):
        """
        image_raw를 jpeg로 인코딩한 뒤 self.frame_sender에 넣음.
        """
        timestamp = time.time_ns()
        self.consecutive_capture_fail_count = 0
        # IMWRITE_JPEG_QUALITY는 jpeg의 품질을 설정함. 0~100 사이 값.
        encoding_success, jpg = cv2.imencode('.jpg', image_raw, [cv2.IMWRITE_JPEG_QUALITY, 85])
        assert encoding_success, "JPEG 인코딩이 성공해야 함"
        self.frame_sender.put_video(timestamp, seq, jpg.tobytes())

class AudioCapturer:
    # 16000 / 512 = 31.25 이므로, 31.25Hz로 메시지 전송.
    AUDIO_FRAME_RATE = 16000
    AUDIO_FRAME_COUNT_PER_CHUNK = 512

    CHANNELS = 1
    
    def __init__(self, frame_sender: FrameSender, device=None):
        self.message_sender = frame_sender
        self.device = device

        self.error_status_count = 0
        """
        sounddevice에서 발생한 에러 수
        """
        self.adc_time_invalid_count = 0

        self.next_seq = 0
        
    
    def __enter__(self):
        self.audio_input_stream = sd.InputStream(
            device=self.device,
            samplerate=AudioCapturer.AUDIO_FRAME_RATE,
            channels=AudioCapturer.CHANNELS,
            dtype=protocol.AUDIO_BYTES_PER_SAMPLE_TYPENAME,
            blocksize=AudioCapturer.AUDIO_FRAME_COUNT_PER_CHUNK,
            callback=self._audio_callback,
        )
        self.audio_frame_rate = int(self.audio_input_stream.samplerate)
        self.audio_input_stream.start()
        print(f"오디오 설정됨. 장치: {self.audio_input_stream.device}")
        print(f"오디오 프레임 레이트: {self.audio_frame_rate}, 지연: {self.audio_input_stream.latency:.4f}s")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.audio_input_stream.stop()
        self.audio_input_stream.close()
    
    def _audio_callback(self, indata, frames, time_info, status):
        # time_info.inputBufferAdcTime: 이 버퍼의 첫 샘플이 ADC를 통과한 시각
        # time_info.currentTime: 콜백이 호출된 시각
        # frames: indata 내의 오디오 프레임 개수
        # status: indata 생성 과정에서 에러가 발생했는지 여부를 나타내는 비트열. 오디오 버퍼 오버플로우 등. 에러가 없으면 00000 값.
        seq = self.next_seq
        self.next_seq += 1
        if status:
            self.error_status_count += 1
        timestamp_ns = self._first_sample_capture_time_ns(time_info, frames)
        pcm = indata.copy().tobytes()  # 버퍼가 재사용되므로 copy 필수
        payload = protocol.pack_audio(self.audio_frame_rate, AudioCapturer.CHANNELS, pcm)
        self.message_sender.put_audio(timestamp_ns, seq, payload)
        
    def _first_sample_capture_time_ns(self, time_info, frame_count):
        """청크 첫 샘플의 취득 시각 time_info.inputBufferTime을 현재 벽시계 기준으로 환산."""
        now_ns = time.time_ns()
        first_sample_age_seconds = None  # 첫 번째 샘플이 만들어진 뒤 콜백 호출까지 걸린 시간
        if time_info.inputBufferAdcTime <= 0:
            # time_info.inputBufferAdcTime이 0을 반환하는 경우가 있음.

            self.adc_time_invalid_count += 1

            # 근사값. 청크 첫 샘플 취득 이후 마지막 샘플 취득까지 걸린 시간만 고려. 마지막 샘플 취득 후 콜백 호출까지 걸린 시간은 무시.
            first_sample_age_seconds = frame_count / self.audio_frame_rate
        else:
            first_sample_age_seconds = time_info.currentTime - time_info.inputBufferAdcTime
        
        return now_ns - int(first_sample_age_seconds * 1e9)



# === 리포트용 코드 ===

_ALERT_FIELDS = (
    # (스냅샷 키, 표시 이름) — 지난 주기보다 늘었으면 경고로 출력한다
    ('video_overflow', '영상버림'),
    ('audio_overflow', '오디오넘침'),
    ('capture_fail',   '캡처실패'),
    ('audio_status',   'status'),
    ('adc_invalid',    'ADC무효'),
)

_LIVENESS_FIELDS = (
    ('sender_alive', '송신'),
    ('video_alive',  '영상캡처'),
    ('audio_alive',  '오디오스트림'),
)


def _snapshot(frame_sender: FrameSender,
              video_capturer: VideoCapturer,
              audio_capturer: AudioCapturer) -> dict:
    """모든 계수기를 한 시점에 함께 읽는다.

    필드를 따로 읽으면 그 사이에 값이 바뀌어 '전송 수 > 캡처 수' 같은
    모순된 줄이 나온다. 계수기가 세 스레드에서 갱신되므로 실제로 발생한다.
    """
    return {
        'video_captured': video_capturer.next_seq,
        'audio_captured': audio_capturer.next_seq,
        'video_sent':     frame_sender.send_success_count(protocol.TYPE_VIDEO_JPEG),
        'audio_sent':     frame_sender.send_success_count(protocol.TYPE_AUDIO_PCM),
        'video_overflow': frame_sender.video_overflow,
        'audio_overflow': frame_sender.audio_overflow,
        'capture_fail':   video_capturer.capture_fail_count,
        'audio_status':   audio_capturer.error_status_count,
        'adc_invalid':    audio_capturer.adc_time_invalid_count,
        'queue_size':     frame_sender.queue.qsize(),
        'video_in_queue': frame_sender.video_in_queue_count.value,
        'sender_alive':   frame_sender.thread.is_alive(),
        'video_alive':    video_capturer.thread.is_alive(),
        'audio_alive':    audio_capturer.audio_input_stream.active,
    }


def _report_loop(frame_sender: FrameSender,
                 video_capturer: VideoCapturer,
                 audio_capturer: AudioCapturer,
                 interval_sec: float = 1.0):
    """주기적으로 전송률과 이상 징후를 출력한다. 데이터 경로에는 개입하지 않는다."""
    start_ns = time.time_ns()
    previous = _snapshot(frame_sender, video_capturer, audio_capturer)
    print('수집 시작. Ctrl+C로 종료.', flush=True)

    while True:
        time.sleep(interval_sec)
        current = _snapshot(frame_sender, video_capturer, audio_capturer)
        elapsed_sec = (time.time_ns() - start_ns) / 1e9

        video_hz = (current['video_sent'] - previous['video_sent']) / interval_sec
        audio_hz = (current['audio_sent'] - previous['audio_sent']) / interval_sec

        line = (f"[{elapsed_sec:6.1f}s] "
                f"영상 {video_hz:5.1f}/s  오디오 {audio_hz:5.1f}/s  "
                f"큐 {current['queue_size']:3d}/{FrameSender.QUEUE_MAX}"
                f"(영상 {current['video_in_queue']:2d}/{FrameSender.VIDEO_IN_QUEUE_MAX})")

        alerts = [f"{label} +{current[key] - previous[key]}(누적 {current[key]})"
                  for key, label in _ALERT_FIELDS
                  if current[key] != previous[key]]
        if alerts:
            line += '  [!] ' + ', '.join(alerts)

        stopped = [label for key, label in _LIVENESS_FIELDS if not current[key]]
        if stopped:
            line += f"  [XX] 정지: {', '.join(stopped)}"
            if frame_sender.send_error is not None:
                line += f" / 송신 오류 {frame_sender.send_error!r}"

        print(line, flush=True)
        previous = current


def _print_summary(frame_sender: FrameSender,
                   video_capturer: VideoCapturer,
                   audio_capturer: AudioCapturer,
                   elapsed_sec: float):
    """종료 시 누적 통계. README에 그대로 옮길 수 있는 형태로 출력한다."""
    final = _snapshot(frame_sender, video_capturer, audio_capturer)
    elapsed_sec = max(elapsed_sec, 1e-9)

    print(f'\n=== 수집 요약 ({elapsed_sec:.1f}초) ===')
    for label, captured_key, sent_key in (
            ('영상  ', 'video_captured', 'video_sent'),
            ('오디오', 'audio_captured', 'audio_sent')):
        captured, sent = final[captured_key], final[sent_key]
        lost = captured - sent
        loss_percent = lost / captured * 100 if captured else 0.0
        print(f'{label}: 캡처 {captured}, 전송 {sent}, '
              f'유실 {lost}({loss_percent:.2f}%), 평균 {sent / elapsed_sec:.2f}Hz')

    for key, label in _ALERT_FIELDS:
        print(f'  {label}: {final[key]}')
    if frame_sender.send_error is not None:
        print(f'  송신 오류: {frame_sender.send_error!r}')



# === 메인 ===

def find_input_device(name_substring: str, hostapi_substring: str | None = None) -> int:
    """이름(및 호스트 API)으로 입력 장치 번호를 찾는다. 번호는 재부팅·재연결 시 바뀐다."""
    for index, device in enumerate(sd.query_devices()):
        if device['max_input_channels'] >= 1 \
        and name_substring.lower() in device['name'].lower():
            api = sd.query_hostapis(device['hostapi'])['name']
            result = None
            if hostapi_substring is None:
                result = index
            elif hostapi_substring.lower() in api.lower():
                result = index
            if result is not None:
                print(f"입력 장치 발견됨: {index:3d}  {api:12s}  {device['name']}")
                return result
    raise RuntimeError(f"입력 장치를 찾지 못함: {name_substring!r} / {hostapi_substring!r}")

def main():
    with FrameSender() as frame_sender:
        audio_capturer = AudioCapturer(frame_sender, device=find_input_device("buds", "WASAPI"))
        video_capturer = VideoCapturer(frame_sender)
        with audio_capturer, video_capturer:
            start_ns = time.time_ns()
            try:
                _report_loop(frame_sender, video_capturer, audio_capturer)
            except KeyboardInterrupt:
                print("종료 중...")
            finally:
                _print_summary(frame_sender, video_capturer, audio_capturer,
                               (time.time_ns() - start_ns) / 1e9)
            
if __name__ == "__main__":
    main()
