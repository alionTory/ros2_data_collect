"""
외부 캡처 시스템으로부터 이미지 데이터를 받아, 포멧을 변환하여 토픽에 발생.
"""
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from data_collect import protocol, topics, qos
from collections import deque
from sensor_msgs.msg import CompressedImage
import socket
import errno
import time
import array
import threading

SOCKET_ACCEPT_RETRYABLE = {errno.ECONNABORTED, errno.EPROTO, errno.EPERM, errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM}

class HostBridge(Node):
    def __init__(self):
        super().__init__('host_bridge')
        self._parameters_setup()

        self.queue = deque(maxlen=self.queue_size)
        """수신된 프레임을 저장해 두는 큐"""
        
        self.overflow_count = 0
        """수신에는 성공했으나, 큐 크기 부족으로 유실된 프레임 개수."""
        
        self.publisher = self.create_publisher(CompressedImage, topics.CAMERA_IMAGE, qos.CAMERA_QOS)

        self.running = True
        """노드를 계속 실행해야 하는지 여부. False이면 노드의 모든 스레드가 종료된다."""
    
        self.expected_next_seq = None
        """
        다음 프레임에 기대되는 seq 번호.
        """

        self.dropped_frame_count = 0
        """
        수신 실패로 유실된 프레임 개수.
        
        단, 연결 해제로 인해 유실된 프레임은 세지 않음. 연결 해제로 인한 유실은 reconnect_count로 추정 가능.
        """

        self.reconnect_count = -1
        """
        연결이 끊긴 후 재접속한 횟수.
        """

        self.invalid_jpeg = 0
        """JPEG 이미지 검증에 실패한 횟수"""

        self.published = 0
        """토픽으로 메시지 발행에 성공한 횟수"""

        threading.Thread(target=self._connect_and_receive, daemon=True).start()
        self.create_timer(0.002, self._deque_and_send)
        self.create_timer(1, self._report)

        
    def _parameters_setup(self):
        self.declare_parameter('port', protocol.DEFAULT_PORT)
        self.declare_parameter('frame_id', 'camera')
        self.declare_parameter('queue_size', 30)

        self.port = self.get_parameter('port').value
        self.frame_id = self.get_parameter('frame_id').value
        self.queue_size = self.get_parameter('queue_size').value

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
        self.expected_next_seq = None
        try:
            while self.running: self._data_receive(connection)
        except (ConnectionError, protocol.ProtocolError, OSError) as ex:
            self.get_logger().warn(f"연결 종료됨. {type(ex).__name__}: {ex}")
        finally:
            connection.close()
                
                
    def _data_receive(self, connection: socket):
        """데이터를 받아 queue에 넣는다."""
        frame = protocol.read_frame(connection)
        if frame.message_type == protocol.TYPE_VIDEO_JPEG:
            if self.expected_next_seq is not None:
                self.dropped_frame_count += frame.seq - self.expected_next_seq
            self.expected_next_seq = frame.seq + 1

            self._append_to_queue(frame)

    def _append_to_queue(self, frame: protocol.Frame):
        """
        queue에 frame을 추가한다.
        
        queue가 가득 찬 상태라면, overflow_count를 1 증가시키고, 가장 오래된 프레임을 큐에서 제거한 후, 큐에 frame을 추가한다.
        """
        if len(self.queue) == self.queue.maxlen:
            self.overflow_count += 1
        self.queue.append(frame)  # 덱이 가득 찬 상태에서, append는 가장 오래된 값을 제거함.
    
    def _deque_and_send(self):
        """queue에서 데이터를 꺼내, 이미지 디코딩 후 토픽에 발행하는 콜백"""
        try:
            frame = self.queue.popleft()
            message = self._image_to_message(frame)
            if message is not None:
                self.publisher.publish(message)
                self.published += 1
        except IndexError:
            pass
            
    def _image_to_message(self, frame: protocol.Frame):
        """
        Frame의 페이로드를 디코딩하여, CompressedImage 메시지로 변환.
        
        디코딩 실패 시, self.decode_failed를 1 증가시키고 None 반환.
        """
        message = None
        if self._validate_jpeg(frame.payload):
            message = CompressedImage()
            # 이미지 캡쳐 프로그램이 이 노드와 같은 기기에서 실행된다고 가정하고, 캡처 측 시간을 메시지에 그대로 저장.
            message.header.stamp = Time(nanoseconds=frame.timestamp_ns).to_msg()
            message.header.frame_id = self.frame_id
            message.format = 'jpeg'
            message.data = array.array('B', frame.payload)
        else:
            self.invalid_jpeg += 1
        return message
    
    def _validate_jpeg(self, jpeg: bytes):
        """
        jpeg 인수가 올바른 JPEG 바이트열인지를 검사해, 올바르다고 판단되면 True를 리턴. 
        
        앞의 두 바이트와 끝의 두 바이트를 통해 검증한다.
        TCP 프레이밍이 잘못 되었음을 감지하는데 사용 가능.
        """
        if jpeg[:2] == b'\xff\xd8' and jpeg[-2:] == b'\xff\xd9':
            return True
        else:
            self.corrupt += 1
            return False
    
    def _report(self):
        """노드 상태를 출력하는 콜백."""
        self.get_logger().info(
            f"발행 성공={self.published}. 유실된 프레임={self.dropped_frame_count}\n"
            f"큐 오버플로={self.overflow_count}. JPEG 검증 실패={self.invalid_jpeg}\n"
            f"캡처 시스템에 재접속={self.reconnect_count}"
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