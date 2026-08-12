"""IMU UDP 수신 및 유실률 산출"""
import socket
import sys
import time
from collections import defaultdict

sys.path.insert(0, "src/data_collect")
from data_collect import protocol


class SeqTracker:
    """한 센서 종류의 시퀀스를 추적한다.

    UDP 는 재정렬과 중복이 정상 동작이므로 순서에 무관한 방식으로 센다.
    """

    def __init__(self):
        self.received = 0
        self.min_seq = None
        self.max_seq = None
        self.duplicates = 0
        self._seen = set()

    def add(self, seq: int):
        self.received += 1
        if seq in self._seen:
            self.duplicates += 1
        self._seen.add(seq)
        if self.min_seq is None or seq < self.min_seq:
            self.min_seq = seq
        if self.max_seq is None or seq > self.max_seq:
            self.max_seq = seq

    def lost(self) -> int:
        # TODO A: (max_seq - min_seq + 1) - 고유 수신 개수
        #         중복이 있으면 self.received 가 아니라 len(self._seen) 을 써야 한다
        return 0

    def loss_rate(self) -> float:
        # TODO B: lost / (max_seq - min_seq + 1)
        return 0.0


NAMES = {
    protocol.TYPE_IMU_ACCEL: "가속도",
    protocol.TYPE_IMU_GYRO: "자이로",
}


def main(port: int = 5556):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(1.0)
    print(f"IMU 수신 대기: 0.0.0.0:{port}")

    trackers = defaultdict(SeqTracker)
    malformed = 0
    last_report = time.monotonic()

    try:
        while True:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                data = None

            if data is not None:
                try:
                    frame = protocol.parse_frame(data)
                    accuracy, x, y, z = protocol.parse_imu(frame.payload)
                    trackers[frame.message_type].add(frame.seq)
                except protocol.ProtocolError as ex:
                    malformed += 1
                    print(f"[형식 오류] {ex}")

            now = time.monotonic()
            if now - last_report >= 1.0:
                last_report = now
                parts = []
                for mtype, name in NAMES.items():
                    t = trackers.get(mtype)
                    if t is None or t.min_seq is None:
                        continue
                    parts.append(
                        f"{name} 수신 {t.received} 유실 {t.lost()} "
                        f"({t.loss_rate() * 100:.2f}%) 중복 {t.duplicates}"
                    )
                if parts:
                    print(" | ".join(parts) + f" | 형식오류 {malformed}")
    except KeyboardInterrupt:
        print("\n=== 최종 ===")
        for mtype, name in NAMES.items():
            t = trackers.get(mtype)
            if t is None or t.min_seq is None:
                print(f"{name}: 수신 없음")
                continue
            span = t.max_seq - t.min_seq + 1
            print(
                f"{name}: seq {t.min_seq}~{t.max_seq} (구간 {span}), "
                f"수신 {t.received}, 고유 {len(t._seen)}, "
                f"유실 {t.lost()} ({t.loss_rate() * 100:.2f}%), 중복 {t.duplicates}"
            )
        print(f"형식 오류 {malformed}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5556)