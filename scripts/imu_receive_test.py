"""IMU UDP 수신 및 유실률 산출.

S3 검증용 도구. ROS 노드가 아니라 단독 스크립트다.

폰이 보낸 개수와 여기서 센 개수를 대조하는 것이 목적이다.
    전송 수 == 수신 수 + 유실 수
"""
import socket
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

# 저장소 어디에서 실행하든 data_collect 패키지를 찾을 수 있게 한다.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src" / "data_collect"))

from data_collect import protocol  # noqa: E402


class SeqTracker:
    """한 센서 종류의 시퀀스와 타임스탬프를 추적한다.

    UDP 는 재정렬과 중복이 정상 동작이므로 순서에 무관한 방식으로 센다.
    (README §7.4)
    """

    def __init__(self):
        self.received = 0          # 받은 패킷 수 (중복 포함)
        self.duplicates = 0
        self.min_seq = None
        self.max_seq = None
        self._seen = set()

        # 소스 기준 주기 계산용. SensorWindow / CaptureWindow 와 같은 방식.
        self.first_ts_ns = None
        self.last_ts_ns = None
        self.backward_ts = 0       # 타임스탬프 역전 (§3.3 ERROR)

    # ── 기록 ────────────────────────────────────────────
    def add(self, seq: int, timestamp_ns: int):
        self.received += 1

        if seq in self._seen:
            self.duplicates += 1
        else:
            self._seen.add(seq)

        if self.min_seq is None or seq < self.min_seq:
            self.min_seq = seq
        if self.max_seq is None or seq > self.max_seq:
            self.max_seq = seq

        if self.first_ts_ns is None:
            self.first_ts_ns = timestamp_ns
        if self.last_ts_ns is not None and timestamp_ns < self.last_ts_ns:
            self.backward_ts += 1
        self.last_ts_ns = timestamp_ns

    # ── 산출 ────────────────────────────────────────────
    @property
    def unique(self) -> int:
        """고유 seq 개수. 중복을 제외한 실제 도달 개수."""
        return len(self._seen)

    @property
    def span(self) -> int:
        """관측된 seq 구간의 크기. 폰이 이 구간에서 보냈어야 할 개수."""
        if self.min_seq is None:
            return 0
        return self.max_seq - self.min_seq + 1

    def lost(self) -> int:
        """유실 개수.

        순서에 무관해야 하므로 '기대값보다 크면 결번' 방식을 쓰지 않는다.
        UDP 에서 재정렬은 고장이 아니라 정상 동작이다.
        """
        return self.span - self.unique

    def loss_rate(self) -> float:
        """유실률. span 이 0 이면 0.0."""
        # TODO B: lost / span
        span = self.span
        if span == 0:
            return 0.0
        else:
            return self.lost() / span

    def source_hz(self):
        """소스(폰) 타임스탬프 기준 평균 주기.

        도착 시각이 아니라 header.timestamp_ns 로 계산한다.
        전달이 밀려도 이 값은 흔들리지 않는다.
        표본이 2개 미만이면 None.
        """
        if self.unique < 2 or self.first_ts_ns is None:
            return None
        elapsed_ns = self.last_ts_ns - self.first_ts_ns
        if elapsed_ns <= 0:
            return None
        return (self.unique - 1) / (elapsed_ns / 1e9)


NAMES = {
    protocol.TYPE_IMU_ACCEL: "가속도",
    protocol.TYPE_IMU_GYRO: "자이로",
}


class Stats:
    """프레임 층·내용 층 오류를 따로 센다. (README §7.4 — 층별 계수기)"""

    def __init__(self):
        self.malformed_frame = 0    # 헤더 파싱 실패, 길이 불일치
        self.malformed_imu = 0      # 페이로드 파싱 실패
        self.unknown_type = 0       # IMU 가 아닌 message_type
        self.trailing_bytes = 0     # 데이터그램에 여분 바이트


def _handle(data: bytes, trackers: dict, stats: Stats) -> None:
    """데이터그램 하나를 해석해 집계한다. 예외를 밖으로 내보내지 않는다."""
    try:
        frame = protocol.parse_frame(data)
    except protocol.ProtocolError as ex:
        stats.malformed_frame += 1
        print(f"[프레임 오류] {ex}")
        return

    # UDP 는 메시지 경계가 보존되므로 길이가 정확히 맞아야 한다.
    # TCP 와 달리 '여분 바이트'는 프레이밍 오류가 아니라 송신 측 버그를 뜻한다.
    expected = protocol.HEADER.size + len(frame.payload)
    if len(data) != expected:
        stats.trailing_bytes += 1
        print(f"[길이 불일치] 데이터그램 {len(data)}B, 헤더 기준 {expected}B")

    if frame.message_type not in NAMES:
        stats.unknown_type += 1
        print(f"[알 수 없는 타입] 0x{frame.message_type:02x}")
        return

    try:
        protocol.parse_imu(frame.payload)
    except (protocol.ProtocolError, struct.error, TypeError) as ex:
        stats.malformed_imu += 1
        print(f"[IMU 페이로드 오류] {ex}")
        return

    trackers[frame.message_type].add(frame.seq, frame.timestamp_ns)


def _format_line(name: str, t: SeqTracker, arrived: int) -> str:
    hz = t.source_hz()
    hz_text = f"{hz:.2f}Hz" if hz is not None else "--"
    return (
        f"{name} 수신 {t.unique} 유실 {t.lost()} ({t.loss_rate() * 100:.2f}%) "
        f"중복 {t.duplicates} | 도착 {arrived}/s 소스 {hz_text}"
    )


def _print_summary(trackers: dict, stats: Stats) -> None:
    print("\n=== 최종 ===")
    for mtype, name in NAMES.items():
        t = trackers.get(mtype)
        if t is None or t.min_seq is None:
            print(f"{name}: 수신 없음")
            continue
        hz = t.source_hz()
        hz_text = f"{hz:.3f}Hz" if hz is not None else "--"
        print(
            f"{name}: seq {t.min_seq}~{t.max_seq} (구간 {t.span})\n"
            f"    수신 {t.received} (고유 {t.unique}, 중복 {t.duplicates})\n"
            f"    유실 {t.lost()} ({t.loss_rate() * 100:.2f}%)\n"
            f"    소스 기준 주기 {hz_text}, 타임스탬프 역전 {t.backward_ts}"
        )
    print(
        f"프레임 오류 {stats.malformed_frame} | IMU 페이로드 오류 {stats.malformed_imu} | "
        f"알 수 없는 타입 {stats.unknown_type} | 길이 불일치 {stats.trailing_bytes}"
    )
    print(
        "\n폰 화면의 '전송 수'와 대조할 것: 전송 수 == 고유 수신 + 유실\n"
        "맞지 않으면 폰의 큐 버림·전송 오류 계수기를 함께 볼 것."
    )


def main(port: int = protocol.IMU_DEFAULT_PORT) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)
    print(f"IMU 수신 대기: 0.0.0.0:{port}  (Ctrl+C 로 종료)")

    trackers = defaultdict(SeqTracker)
    stats = Stats()

    last_report = time.monotonic()
    arrived_since_report = defaultdict(int)

    try:
        while True:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                data = None

            if data is not None:
                before = {m: t.received for m, t in trackers.items()}
                _handle(data, trackers, stats)
                for mtype, t in trackers.items():
                    if t.received != before.get(mtype, 0):
                        arrived_since_report[mtype] += 1

            now = time.monotonic()
            elapsed = now - last_report
            if elapsed >= 1.0:
                last_report = now
                parts = [
                    _format_line(name, trackers[mtype],
                                 round(arrived_since_report[mtype] / elapsed))
                    for mtype, name in NAMES.items()
                    if mtype in trackers and trackers[mtype].min_seq is not None
                ]
                if parts:
                    print(" || ".join(parts))
                arrived_since_report.clear()
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        _print_summary(trackers, stats)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else protocol.IMU_DEFAULT_PORT)
