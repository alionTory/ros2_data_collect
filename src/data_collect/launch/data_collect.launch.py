from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(package='data_collect', executable='dummy_camera', name='dummy_camera', output='screen', emulate_tty=True,
            parameters=[{'width': 100, 'height': 100}]
        ),
        Node(package='data_collect', executable='dummy_audio', name='dummy_audio', output='screen', emulate_tty=True),
    ])