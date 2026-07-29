"""
프로토콜 정의 파일. 데이터 캡처 측과 수집 측 간의 통신에 사용됨.
"""
import struct
import socket
from typing import NamedTuple

DEFAULT_PORT = 5555

HEADER = struct.Struct('>IBqq')
'''
헤더
> : 빅 엔디안, 패딩 없음.
I : payload_len unsigned 4 byte
B : message_type unsigned 1 byte
q : timestamp_ns signed 8 byte
q : seq (메시지 순서 번호) signed 8 byte
'''

TYPE_HELLO = 0x00
TYPE_VIDEO_JPEG = 0x01
TYPE_AUDIO_PCM = 0x02
TYPE_SYNC_PING = 0x10
TYPE_SYNC_PONG = 0x11
TYPE_SYNC_REPORT = 0x12

MAX_PAYLOAD = 1 << 20  # 1MB
"""
페이로드 바이트 길이 상한.
프레이밍이 깨지면 대용량의 쓰레기값을 읽다 프로세스가 크래시될 수 있음. 이를 방지하기 위한 용도.
"""

class ProtocolError(Exception):
    """프레임 구조가 규약에 맞지 않음"""

class Frame(NamedTuple):
    message_type: int
    timestamp_ns: int
    seq: int
    payload: bytes

def pack_frame(message_type: int, timestamp_ns: int, seq: int, payload: bytes) -> bytes:
    """바이트 시퀀스 데이터 생성"""
    return HEADER.pack(len(payload), message_type, timestamp_ns, seq) + payload

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

def recv_exact(sock: socket.socket, n: int) -> bytes:
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
    buffer = recv_exact(sock, HEADER.size)
    length, message_type, timestamp_ns, seq = HEADER.unpack_from(buffer)
    if MAX_PAYLOAD < length:
        raise ProtocolError(f"payload 길이 {length}가 최대 길이 {MAX_PAYLOAD}를 넘음.")
    payload = recv_exact(sock, length)
    return Frame(
        message_type=message_type,
        timestamp_ns=timestamp_ns,
        seq=seq,
        payload=payload,
    )

def send_frame(sock: socket.socket, message_type: int, timestamp_ns: int, seq: int, payload: bytes):
    """프레임을 sock으로 전송"""
    buffer = pack_frame(message_type, timestamp_ns, seq, payload)
    sock.sendall(buffer)

if __name__ == "__main__":
    # 왕복 테스트
    fake_jpg = bytes(range(256))*100
    fake_timestamp = 1785_000_000_000_000_000
    frame = parse_frame(pack_frame(TYPE_VIDEO_JPEG, fake_timestamp, 7, fake_jpg))
    assert frame == (TYPE_VIDEO_JPEG, fake_timestamp, 7, fake_jpg)
    print("ok. header size = ", HEADER.size)