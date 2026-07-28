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
from queue import Queue

class VideoCapturer:
    MAX_CONSECUTIVE_CAPTURE_FAILURE = 30
    def __init__(self):
        self.seq = 0
        self.capture_fail_count = 0
        self.consecutive_capture_fail_count = 0
    
    def __enter__(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("카메라를 사용할 수 없습니다.")
            exit()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(('127.0.0.1', protocol.DEFAULT_PORT))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # TCP Nagle을 비활성화해 지연 감소.

        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.sock.close()
        self.cap.release()
    
    def start_capture(self):
        while True:
            capture_success, frame = self.cap.read()
            if capture_success:
                self._send_jpeg(frame)
            else:
                self._process_capture_failure()
    
    def _process_capture_failure(self):
        self.capture_fail_count += 1
        self.consecutive_capture_fail_count += 1
        if VideoCapturer.MAX_CONSECUTIVE_CAPTURE_FAILURE <= self.consecutive_capture_fail_count:
            raise RuntimeError(f"카메라 프레임 캡처 {self.consecutive_capture_fail_count}번 연속 실패")
        time.sleep(0.01)

    def _send_jpeg(self, frame):
        timestamp = time.time_ns()
        self.consecutive_capture_fail_count = 0
        # IMWRITE_JPEG_QUALITY는 jpeg의 품질을 설정함. 0~100 사이 값.
        encoding_success, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        assert encoding_success, "JPEG 인코딩이 성공해야 함"
        protocol.send_frame(self.sock, protocol.TYPE_VIDEO_JPEG, timestamp, self.seq, jpg.tobytes())
        self.seq += 1
        

def main():
    with VideoCapturer() as video_capturer:
        video_capturer.start_capture()

main()