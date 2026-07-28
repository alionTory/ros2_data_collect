import sys
import rclpy
import numpy as np
from rclpy.node import Node
from data_collect_msgs.msg import AudioChunk
from data_collect import qos
from numpy.typing import NDArray
import array

CHANNELS = 1

class DummyAudio(Node):
    def __init__(self):
        super().__init__("dummy_audio")
        self._set_parameter()
        self.sine_offset = 0
        self.publisher = self.create_publisher(AudioChunk, '/sensors/audio/chunk', qos.AUDIO_QOS)
        chunk_period = self.sample_count / self.sample_rate
        self.timer = self.create_timer(chunk_period, self.on_tick)

    def _set_parameter(self):
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('sample_count', 512)
        self.declare_parameter('sine_frequency', 440.0)
        self.declare_parameter('sine_amplitude', 8000.0)

        self.sample_rate = self.get_parameter('sample_rate').value
        self.sample_count = self.get_parameter('sample_count').value
        self.sine_frequency = self.get_parameter('sine_frequency').value
        self.sine_amplitude = self.get_parameter('sine_amplitude').value
        
    def on_tick(self):
        msg = AudioChunk()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "microphone"

        msg.sample_rate = self.sample_rate
        msg.sample_count = self.sample_count
        msg.channels = CHANNELS

        buf = array.array('h')  # s'h'ort, 즉 int16 배열
        buf.frombytes(self._make_sine_wave().tobytes())
        msg.data = buf

        self.publisher.publish(msg)

    def _make_sine_wave(self) -> NDArray[np.int16]:
        t = np.arange(self.sample_count) / self.sample_rate
        result = np.sin(2*np.pi*self.sine_frequency*t + self.sine_offset) * self.sine_amplitude
        self.sine_offset += 2*np.pi*self.sine_frequency*self.sample_count/self.sample_rate
        self.sine_offset %= 2*np.pi
        return result.round().astype(np.int16)

def main(args=None):
    rclpy.init(args=args)
    node = DummyAudio()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main(sys.argv)