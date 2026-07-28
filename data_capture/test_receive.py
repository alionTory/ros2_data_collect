import socket
import sys
import time

sys.path.insert(0, '/home/aliontory/ros2_data_collect/src/data_collect')
from data_collect import protocol as P

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('0.0.0.0', P.DEFAULT_PORT))
srv.listen(1)
print(f'포트 {P.DEFAULT_PORT} 대기 중...')

conn, addr = srv.accept()
print('접속:', addr)

n = expect = dropped = nbytes = 0
t0 = time.time()
try:
    while True:
        f = P.read_frame(conn)
        if f.seq != expect:
            dropped += f.seq - expect
        expect = f.seq + 1
        n += 1
        nbytes += len(f.payload)

        if n == 100:
            with open('/tmp/frame100.jpg', 'wb') as fp:
                fp.write(f.payload)

        if n % 30 == 0:
            hz = n / (time.time() - t0)
            lat_ms = (time.time_ns() - f.timestamp_ns) / 1e6
            print(f'{n:5d}프레임  {hz:5.1f}Hz  유실={dropped}  '
                  f'평균={nbytes // n}B  지연={lat_ms:6.1f}ms')
except (KeyboardInterrupt, ConnectionError, P.ProtocolError) as e:
    print('종료:', type(e).__name__, e)