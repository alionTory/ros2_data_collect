from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy, QoSHistoryPolicy

# 영상 프레임은 독립적이고 대용량이므로, 유실은 시퀀스 번호로 검출하고 재전송하지 않는다.
CAMERA_QOS = QoSProfile(
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
)

# 오디오는 연속 신호. 한 청크 유실이 주변 구간까지 오염시키므로 재전송한다.
AUDIO_QOS = QoSProfile(
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=10,
    reliability=QoSReliabilityPolicy.RELIABLE,
)

# IMU는 소용량, 보간 가능.
IMU_QOS = QoSProfile(
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=20,
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
)

# 1Hz 상태값.
CLOCK_OFFSET_QOS = QoSProfile(
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
    reliability=QoSReliabilityPolicy.RELIABLE,

    # 나중에 접속한 구독자라도 마지막 샘플을 보낸다.
    # 이게 없으면 나중에 접속한 구독자는 최대 1초 동안 오프셋을 모른 채 동작하게 됨
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
)