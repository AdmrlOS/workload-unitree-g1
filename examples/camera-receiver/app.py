"""Receive stock G1 H.264 multicast without competing for the USB camera.

This dependency-free starter observes packet arrival only. It does not decode
frames, control motion, or claim that received bytes are valid H.264 frames.
"""
import os
import signal
import socket
import struct
import time

running = True


def stop(*_):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    interface = os.environ.get('ROBOT_INTERFACE', 'eth0')
    group, port = '230.1.1.1', 1720
    print(f'camera receiver: uid={os.getuid()}, listening on {interface} {group}:{port}', flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', port))
        # Linux ip_mreqn chooses the NIC without assuming its IP address.
        membership = struct.pack('=4s4si', socket.inet_aton(group), b'\0' * 4,
                                 socket.if_nametoindex(interface))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.settimeout(1)
        packets = size = 0
        report_at = time.monotonic() + 5
        while running:
            try:
                payload, _ = sock.recvfrom(65535)
                packets += 1
                size += len(payload)
            except socket.timeout:
                pass
            if time.monotonic() >= report_at:
                print(f'camera receiver: {packets} packets / {size} bytes in last 5s', flush=True)
                packets = size = 0
                report_at = time.monotonic() + 5
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, membership)
    print('camera receiver: stopped', flush=True)


if __name__ == '__main__':
    main()
