"""
외부 캡처 시스템으로부터 이미지 데이터를 받아, 포멧을 변환하여 토픽에 발생.
"""
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from data_collect import protocol, topics, qos
from collections import deque
from sensor_msgs.msg import CompressedImage
from data_collect_msgs.msg import AudioChunk
import socket
import errno
import time
import array
import threading
import struct
import sys

SOCKET_ACCEPT_RETRYABLE = {errno.ECONNABORTED, errno.EPROTO, errno.EPERM, errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM}

class FrameQueue:
    def __init__(self, video_queue_size, audio_queue_size):
        self._video_queue = deque(maxlen=video_queue_size)
        """수신된 비디오 프레임을 저장해 두는 큐"""
        self._audio_queue = deque(maxlen=audio_queue_size)
        """수신된 오디오 청크를 저장해 두는 큐"""

        self._queue_size = {protocol.TYPE_VIDEO_JPEG: video_queue_size, protocol.TYPE_AUDIO_PCM: audio_queue_size}

        self.overflow_count = {protocol.TYPE_VIDEO_JPEG: 0, protocol.TYPE_AUDIO_PCM: 0}
        """수신에는 성공했으나, 큐 크기 부족으로 유실된 프레임 개수."""

    def enqueue(self, frame: protocol.Frame):
        """
        queue에 frame을 추가한다.
        
        queue가 가득 찬 상태라면, _overflow_count를 1 증가시키고, 가장 오래된 프레임을 큐에서 제거한 후, 큐에 frame을 추가한다.
        """
        queue = None
        if frame.message_type == protocol.TYPE_VIDEO_JPEG:
            queue = self._video_queue
        elif frame.message_type == protocol.TYPE_AUDIO_PCM:
            queue = self._audio_queue

        if len(queue) == self._queue_size[frame.message_type]:
            self.overflow_count[frame.message_type] += 1
        queue.append(frame)  # 덱이 가득 찬 상태에서, append는 가장 오래된 값을 제거함.
    
    def dequeue(self) -> protocol.Frame:
        """
        Raises:
            IndexError: 큐가 비어 있는 경우.
        """
        try:
            return self._audio_queue.popleft()
        except IndexError:
            pass
        return self._video_queue.popleft()
            
    def get_status(self) -> str:
        return f"비디오 넘침={self.overflow_count[protocol.TYPE_VIDEO_JPEG]} 큐={len(self._video_queue)}\n" \
        + f"오디오 넘침={self.overflow_count[protocol.TYPE_AUDIO_PCM]} 큐={len(self._audio_queue)}"
        

class HostBridge(Node):
    def __init__(self):
        super().__init__('host_bridge')
        self._parameters_setup()
        self.running = True
        """노드를 계속 실행해야 하는지 여부. False이면 노드의 모든 스레드가 종료된다."""

        self.queue = FrameQueue(self.video_queue_size, self.audio_queue_size)

        self.expected_next_seq: dict[int, int] = {}
        """
        다음 프레임에 기대되는 seq 번호. 재접속 시 비워진다.
        """
        
        self.dropped_frame_count = {protocol.TYPE_VIDEO_JPEG: 0, protocol.TYPE_AUDIO_PCM: 0}
        """
        수신 실패로 유실된 프레임 개수.
        
        단, 연결 해제로 인해 유실된 프레임은 세지 않음. 연결 해제로 인한 유실은 reconnect_count로 추정 가능.
        """
        self.published = {protocol.TYPE_VIDEO_JPEG: 0, protocol.TYPE_AUDIO_PCM: 0}
        """토픽으로 메시지 발행에 성공한 횟수"""
        self.invalid_format = {protocol.TYPE_VIDEO_JPEG: 0, protocol.TYPE_AUDIO_PCM: 0}
        """데이터 포맷 검증에 실패한 횟수"""

        self.unknown_frame_type_count = 0
        
        self.reconnect_count = -1
        """
        연결이 끊긴 후 재접속한 횟수.
        """

        self.image_publisher = self.create_publisher(CompressedImage, topics.CAMERA_IMAGE, qos.CAMERA_QOS)
        self.audio_publisher = self.create_publisher(AudioChunk, topics.AUDIO_CHUNK, qos.AUDIO_QOS)
        self.publisher = {protocol.TYPE_VIDEO_JPEG: self.image_publisher, protocol.TYPE_AUDIO_PCM: self.audio_publisher}

        threading.Thread(target=self._connect_and_receive, daemon=True).start()
        self.create_timer(0.002, self._deque_and_send)
        self.create_timer(1, self._report)

        
    def _parameters_setup(self):
        self.declare_parameter('port', protocol.DEFAULT_PORT)
        self.declare_parameter('video_frame_id', 'camera')
        self.declare_parameter('video_queue_size', 30)
        self.declare_parameter('audio_frame_id', 'microphone')
        self.declare_parameter('audio_queue_size', 400)

        self.port = self.get_parameter('port').value
        self.video_frame_id = self.get_parameter('video_frame_id').value
        self.video_queue_size = self.get_parameter('video_queue_size').value
        self.audio_frame_id = self.get_parameter('audio_frame_id').value
        self.audio_queue_size = self.get_parameter('audio_queue_size').value

    def _connect_and_receive(self):
        """외부 시스템으로부터 데이터를 받아오는 스레드"""
        self._initialize_server_socket()

        while self.running:
            connection = None
            try:
                connection, address = self.server_socket.accept()
            except OSError as ex:
                self._handle_accept_fail(ex)
                    
            if connection is not None:
                self._handle_connection(connection, address)
        
    def _initialize_server_socket(self):
        """self.server_socket을 초기화하고 리스닝 시작."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # 포트 상태가 TCP TIME_WAIT 라도 바로 재사용하도록 함.
        # 이 옵션이 없으면 프로세스 종료 직후 재시작 시 수십 초 이상 포트 바인딩에 실패할 수 있음.
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("0.0.0.0", self.port))
        self.server_socket.listen(1)  # 연결 요청을 저장할 큐의 크기 1
        self.get_logger().info(f"포트 {self.port} 대기 중.")
    
    def _handle_accept_fail(self, ex: OSError):
        """
        self.running이 False인 경우, 정상 종료이므로 바로 리턴.

        self.running이 True 인 경우, 
            재시도 가능한 에러인 경우에는 0.1초 대기 후 리턴.
            재시도 불가능한 경우 self.running을 False로 바꾸고 리턴.
        """
        if not self.running:
            self.get_logger().info(f"데이터 수신 스레드를 종료합니다.")
        elif ex.errno in SOCKET_ACCEPT_RETRYABLE:
            self.get_logger().warn(f"소켓 accept 실패: {ex}")
            self.get_logger().warn("accept 재시도.")
            time.sleep(0.1)
        else:
            self.get_logger().fatal(f"소켓에 문제 발생: {ex}")
            self.get_logger().fatal(f"노드 종료")
            self.running = False
    
    def _handle_connection(self, connection: socket, address):
        """
        클라이언트로부터 반복적인 데이터 수신 시작.

        연결 종료 또는 self.running이 False가 될 경우, 연결 소켓을 닫은 뒤 리턴.
        """
        self.get_logger().info(f"소켓에 클라이언트가 접속함. 주소: {address}")
        self.reconnect_count += 1
        self.expected_next_seq = {}
        try:
            while self.running: self._data_receive(connection)
        except (ConnectionError, protocol.ProtocolError, OSError) as ex:
            self.get_logger().warn(f"연결 종료됨. {type(ex).__name__}: {ex}")
        finally:
            connection.close()
                
                
    def _data_receive(self, connection: socket):
        """데이터를 받아 queue에 넣는다."""
        frame = protocol.read_frame(connection)
        if HostBridge._is_known_type(frame.message_type):
            if frame.message_type in self.expected_next_seq:
                self.dropped_frame_count[frame.message_type] += frame.seq - self.expected_next_seq[frame.message_type]
            self.expected_next_seq[frame.message_type] = frame.seq + 1

            self.queue.enqueue(frame)
        else:
            self.unknown_frame_type_count += 1
    
    @staticmethod
    def _is_known_type(frame_type):
        return frame_type in [protocol.TYPE_VIDEO_JPEG, protocol.TYPE_AUDIO_PCM]

    def _deque_and_send(self):
        """queue에서 데이터를 꺼내, 이미지 검증 후 토픽에 발행하는 콜백"""
        try:
            frame = self.queue.dequeue()
            message = self._frame_to_message(frame)
            if message is not None:
                self.publisher[frame.message_type].publish(message)
                self.published[frame.message_type] += 1
        except IndexError:
            pass
    
    def _frame_to_message(self, frame: protocol.Frame):
        if frame.message_type == protocol.TYPE_VIDEO_JPEG:
            self._image_to_message(frame)
        elif frame.message_type == protocol.TYPE_AUDIO_PCM:
            self._image_to_message(frame)
        else:
            assert False
            
    def _image_to_message(self, frame: protocol.Frame):
        """
        Frame의 페이로드를 검증하여, CompressedImage 메시지로 변환.
        
        검증 실패 시 None 반환.
        """
        message = None
        if self._validate_jpeg(frame.payload):
            message = CompressedImage()
            # 이미지 캡쳐 프로그램이 이 노드와 같은 기기에서 실행된다고 가정하고, 캡처 측 시간을 메시지에 그대로 저장.
            message.header.stamp = Time(nanoseconds=frame.timestamp_ns).to_msg()
            message.header.frame_id = self.video_frame_id
            message.format = 'jpeg'
            message.data = array.array('B', frame.payload)
        return message
    
    def _validate_jpeg(self, jpeg: bytes):
        """
        jpeg 인수가 올바른 JPEG 바이트열인지를 검사해, 올바르다고 판단되면 True를 리턴. 
        
        검증 실패 시, self.invalid_jpeg를 1 증가시킨다.

        앞의 두 바이트와 끝의 두 바이트를 통해 검증한다.
        TCP 프레이밍이 잘못 되었음을 감지하는데 사용 가능.
        """
        if jpeg[:2] == b'\xff\xd8' and jpeg[-2:] == b'\xff\xd9':
            return True
        else:
            self.invalid_format[protocol.TYPE_VIDEO_JPEG] += 1
            return False
    
    def _audio_to_message(self, frame: protocol.Frame):
        """
        Frame의 페이로드를 검증하여, AudioChunk 메시지로 변환.
        
        검증 실패 시 None 반환.
        """
        try:
            sample_rate, channels, sample_count, pcm = protocol.parse_audio(frame.payload)
        except protocol.ProtocolError:
            self.invalid_format[protocol.TYPE_AUDIO_PCM] += 1
            return None
        
        samples = array.array(protocol.AUDIO_BYTES_PER_SAMPLE_CODE)
        samples.frombytes(pcm)
        if sys.byteorder == 'big':
            samples.byteswap()

        message = AudioChunk()
        message.header.stamp = Time(nanoseconds=frame.timestamp_ns).to_msg()
        message.header.frame_id = self.audio_frame_id
        message.sample_rate = sample_rate
        message.channels = channels
        message.sample_count = sample_count
        message.data = samples
        return message

    
    def _report(self):
        """노드 상태를 출력하는 콜백."""
        video, audio = protocol.TYPE_VIDEO_JPEG, protocol.TYPE_AUDIO_PCM
        self.get_logger().info(
            f"영상 발행={self.published[video]} 유실={self.dropped_frame_count[video]} JPEG오류={self.invalid_format[video]}  | "
            f"오디오 발행={self.published[audio]} 유실={self.dropped_frame_count[audio]} 청크오류={self.invalid_format[audio]}  | "
            f"큐 상태: | " \
            + self.queue.get_status() + \
            f"재접속={self.reconnect_count} 미지원타입={self.unknown_frame_type_count}"
        )
    
    def destroy_node(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        super().destroy_node()
            
        
                
def main(args=None):
    rclpy.init(args=args)
    node = HostBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()