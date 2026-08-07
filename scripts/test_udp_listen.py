import socket, sys
port = int(sys.argv[1]) if len(sys.argv) > 1 else 5556
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", port))
print(f"listening on 0.0.0.0:{port}")
while True:
    data, addr = s.recvfrom(2048)
    print(f"{addr}  {len(data)}B  {data[:64]!r}")