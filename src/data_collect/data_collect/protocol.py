"""
프로토콜 정의 파일. 데이터 캡처 측과 수집 측 간의 통신에 사용됨.
"""
import struct
import socket
from typing import NamedTuple

HEADER = struct.Struct('>IBqq')
"""
프레임 헤더
    빅 엔디안, 패딩 없음. (>)
    payload_len (I): unsigned int32 
    message_type (B): unsigned int8 
    timestamp_ns (q): signed int64
    seq (메시지 순서 번호) (q): signed int64
"""

TYPE_HELLO = 0x00
TYPE_VIDEO_JPEG = 0x01
TYPE_AUDIO_PCM = 0x02
TYPE_IMU_ACCEL = 0x03
TYPE_IMU_GYRO  = 0x04
TYPE_SYNC_PING = 0x10
TYPE_SYNC_PONG = 0x11
TYPE_SYNC_REPORT = 0x12

MAX_PAYLOAD = 1 << 20  # 1MB
"""
페이로드 바이트 길이 상한.
프레이밍이 깨지면 대용량의 쓰레기값을 읽다 프로세스가 크래시될 수 있음. 이를 방지하기 위한 용도.
"""

AUDIO_SUBHEADER = struct.Struct('>IHI')
"""
오디오용 서브헤더
    빅 엔디안, 패딩 없음.
    frame_rate (I): unsigned int32
    channels (H): unsigned int16
    frame_count (I): unsigned int32

주의: 오디오 페이로드 PCM은 리틀 엔디안 int16임.
"""

AUDIO_BYTES_PER_SAMPLE = 2
AUDIO_BYTES_PER_SAMPLE_TYPENAME = 'int16'
AUDIO_BYTES_PER_SAMPLE_CODE = 'h'

DEFAULT_PORT = 5555
"""외부 센서로부터 비디오 및 오디오 데이터를 수신받는 ROS2 노드에서 열 포트 번호."""

IMU_SUBHEADER = struct.Struct('>Bfff')
"""
IMU 샘플용 서브헤더
    빅 엔디안, 패딩 없음.
    accuracy (B): unsigned int8
    x, y, z (f): float32
"""

IMU_DEFAULT_PORT = 5556
"""외부 센서로부터 IMU 데이터를 수신하는 ROS 노드에서 열 포트 번호"""


class ProtocolError(Exception):
    """프레임 구조가 규약에 맞지 않음"""

class Frame(NamedTuple):
    message_type: int
    timestamp_ns: int
    seq: int
    payload: bytes
    
    def pack(self):
        """바이트 시퀀스 데이터 생성"""
        return HEADER.pack(len(self.payload), self.message_type, self.timestamp_ns, self.seq) + self.payload
    
    def send(self, sock: socket.socket):
        """프레임을 sock으로 전송"""
        buffer = self.pack()
        sock.sendall(buffer)

def parse_frame(buffer: bytes) -> Frame:
    """바이트 시퀀스 데이터를 Frame 객체로 변환"""
    if len(buffer) < HEADER.size:
        raise ProtocolError(f"버퍼가 헤더보다 짧음. 버퍼 길이: {len(buffer)}")
    length, message_type, timestamp_ns, seq = HEADER.unpack_from(buffer)
    payload = buffer[HEADER.size : (HEADER.size + length)]
    if len(payload) < length:
        raise ProtocolError(f"payload 길이{len(payload)}가 헤더의 payload_len에 적힌 길이 {length} 보다 작음.")
    return Frame(
        message_type=message_type,
        timestamp_ns=timestamp_ns,
        seq=seq,
        payload=payload,
    )

class Audio(NamedTuple):
    frame_rate: int
    channels: int
    frame_count: int
    pcm: bytes
    
    @classmethod
    def make(cls, frame_rate: int, channels: int, pcm: bytes):
        """Audio 객체를 생성한다. frame_count 필드 값은 pcm 길이와 channels 값으로부터 직접 계산한다."""
        frame_count = len(pcm) // (channels * AUDIO_BYTES_PER_SAMPLE)
        return cls(frame_rate=frame_rate, channels=channels, frame_count=frame_count, pcm=pcm)

    def pack(self) -> bytes:
        assert len(self.pcm) % (self.channels * AUDIO_BYTES_PER_SAMPLE) == 0
        return AUDIO_SUBHEADER.pack(self.frame_rate, self.channels, self.frame_count) + self.pcm

def parse_audio(payload: bytes):
    """
    바이트 시퀀스를 AUDIO_SUBHEADER와 pcm으로 해석하고, PCM 길이가 헤더 정보와 일치하는지 검증.
    
    PCM 길이가 헤더 정보와 다르면 ValueError 예외를 던짐.
    """
    try:
        frame_rate, channels, frame_count = AUDIO_SUBHEADER.unpack_from(payload)
    except struct.error as ex:
        raise ProtocolError(f"payload 길이 {len(payload)}가 헤더 길이 {AUDIO_SUBHEADER.size}보다 짧음.") from ex
    pcm = payload[AUDIO_SUBHEADER.size:]
    if len(pcm) != frame_count * channels * AUDIO_BYTES_PER_SAMPLE:
        raise ProtocolError(f"PCM 길이 {len(pcm)}이 frame_count * channels * AUDIO_BYTES_PER_SAMLE 값 {frame_count * channels * AUDIO_BYTES_PER_SAMPLE}와 불일치.")
    return Audio.make(frame_rate=frame_rate, channels=channels, pcm=pcm)

class Imu(NamedTuple):
    accuracy: int
    x: float
    y: float
    z: float
    
    def pack(self):
        return IMU_SUBHEADER.pack(self.accuracy, self.x, self.y, self.z)

def parse_imu(payload: bytes):
    try:
        return Imu(*IMU_SUBHEADER.unpack_from(payload))
    except struct.error as ex:
        raise ProtocolError(f"payload 길이 {len(payload)}가 헤더 길이 {AUDIO_SUBHEADER.size}보다 짧음.") from ex
    

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """n 바이트가 모일 때까지 socket에서 값을 읽음."""
    buffer = bytearray()  # 가변 바이트 배열
    while len(buffer) < n:
        chunk = sock.recv(n - len(buffer))
        if not chunk:
            raise ConnectionError('peer closed')
        buffer += chunk
    return bytes(buffer)

def read_frame(sock: socket.socket) -> Frame:
    """소켓에서 프레임 데이터를 읽음."""
    buffer = _recv_exact(sock, HEADER.size)
    length, message_type, timestamp_ns, seq = HEADER.unpack_from(buffer)
    if MAX_PAYLOAD < length:
        raise ProtocolError(f"payload 길이 {length}가 최대 길이 {MAX_PAYLOAD}를 넘음.")
    payload = _recv_exact(sock, length)
    return Frame(
        message_type=message_type,
        timestamp_ns=timestamp_ns,
        seq=seq,
        payload=payload,
    )

if __name__ == "__main__":
    # 왕복 테스트
    fake_jpg = bytes(range(256))*100
    fake_timestamp = 1785_000_000_000_000_000
    frame = parse_frame(Frame(TYPE_VIDEO_JPEG, fake_timestamp, 7, fake_jpg).pack())
    assert frame == (TYPE_VIDEO_JPEG, fake_timestamp, 7, fake_jpg)
    print("ok. header size = ", HEADER.size)