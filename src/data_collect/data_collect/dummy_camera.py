import sys
import rclpy
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import Image
from data_collect import qos, topics

class DummyCamera(Node):
    def __init__(self):
        super().__init__("dummy_camera")
        self._parameters_setup()
        self.dummy_image = np.zeros((self.height, self.width, 3), np.uint8).tobytes()
        self.publisher = self.create_publisher(Image, topics.CAMERA_IMAGE, qos.CAMERA_QOS)
        self.timer = self.create_timer(1 / self.fps, self.on_tick)

    def _parameters_setup(self):
        self.declare_parameter('fps', 30)
        self.declare_parameter('width', 800)
        self.declare_parameter('height', 600)

        self.fps = self.get_parameter('fps').value
        self.width = self.get_parameter('width').value
        self.height = self.get_parameter('height').value
        
    def on_tick(self):
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        self.__set_dummy_image(msg)
        msg.encoding = 'bgr8'
        msg.is_bigendian = 0  # 리틀 엔디안
        msg.step = self.width * 3  # 한 행의 바이트 수
        self.publisher.publish(msg)

    def __set_dummy_image(self, msg:Image):
        msg.width = self.width
        msg.height = self.height
        msg.data = self.dummy_image

def main(args=None):
    rclpy.init(args=args)
    node = DummyCamera()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main(sys.argv)