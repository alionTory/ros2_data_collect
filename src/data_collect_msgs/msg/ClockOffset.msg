std_msgs/Header header
string device_id
int64  offset_ns    # ros_time = device_time + offset_ns
int64  rtt_ns       # 추정에 사용된 왕복 시간
float64 confidence  # 최근 샘플의 오프셋 표준편차 기반