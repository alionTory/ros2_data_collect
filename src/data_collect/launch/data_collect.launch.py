from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(package='data_collect', executable='host_bridge', name='host_bridge', output='screen', emulate_tty=True),
    ])