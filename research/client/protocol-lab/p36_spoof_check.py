"""P36: raw-socket source-spoofing self-test (must run as root on macOS).

Sends UDP datagrams with a spoofed source address via a raw socket and reports
which of several destinations actually deliver to a local listener.
Usage: sudo /usr/bin/python3 p36_spoof_check.py [--spoof 10.255.255.254]
"""
import argparse
import json
import socket
import struct
import threading
import time


def ip_checksum(hdr: bytes) -> int:
    if len(hdr) % 2:
        hdr += b'\x00'
    total = 0
    for i in range(0, len(hdr), 2):
        total += (hdr[i] << 8) + hdr[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def build(src_ip, dst_ip, sport, dport, payload):
    udp = struct.pack('>HHHH', sport, dport, 8 + len(payload), 0) + payload
    total = 20 + len(udp)
    iph = struct.pack('>BBHHHBBH4s4s', 0x45, 0, total, 0x1234, 0, 64, 17, 0,
                      bytes(int(p) for p in src_ip.split('.')),
                      bytes(int(p) for p in dst_ip.split('.')))
    csum = ip_checksum(iph)
    iph = iph[:10] + struct.pack('>H', csum) + iph[12:]
    return iph + udp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spoof', default='10.255.255.254')
    ap.add_argument('--spoof-port', type=int, default=9999)
    args = ap.parse_args()

    # local targets to try
    targets = ['127.0.0.1', '127.0.0.2']
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 53))
        targets.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        import re
        import subprocess
        out = subprocess.run(['ifconfig', 'en0'], capture_output=True, text=True).stdout
        m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
        if m and m.group(1) not in targets:
            targets.append(m.group(1))
    except Exception:
        pass
    results = {'targets': targets, 'spoof': [args.spoof, args.spoof_port], 'attempts': []}

    for dst in targets:
        ls = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ls.bind(('0.0.0.0', 0))
        port = ls.getsockname()[1]
        ls.settimeout(3)
        got = {}

        def recv():
            try:
                data, src = ls.recvfrom(2048)
                got.update({'data': data.decode('latin1'), 'seen_src': list(src)})
            except socket.timeout:
                got.update({'error': 'timeout'})

        t = threading.Thread(target=recv, daemon=True)
        t.start()
        time.sleep(0.2)
        rs = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
        rs.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        pkt = build(args.spoof, dst, args.spoof_port, port, b'SPOOF-SELFTEST')
        try:
            n = rs.sendto(pkt, (dst, 0))
        except OSError as e:
            n = repr(e)
        rs.close()
        t.join(4)
        ls.close()
        results['attempts'].append({'dst': dst, 'port': port, 'sent': n, 'observed': got})
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
