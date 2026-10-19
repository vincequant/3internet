"""P36: try three macOS raw-send modes with a spoofed source."""
import json
import socket
import struct
import sys


def ip_checksum(hdr: bytes) -> int:
    if len(hdr) % 2:
        hdr += b'\x00'
    total = 0
    for i in range(0, len(hdr), 2):
        total += (hdr[i] << 8) + hdr[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def main():
    spoof_ip, spoof_port = '36.151.147.251', 29100
    dst_ip, dst_port = '192.168.188.129', 46999
    results = {}

    # V1: IPPROTO_UDP + IP_HDRINCL (full IP header)
    try:
        payload = b'MODE-HDRINCL'
        udp = struct.pack('>HHHH', spoof_port, dst_port, 8 + len(payload), 0) + payload
        total = 20 + len(udp)
        iph = struct.pack('>BBHHHBBH4s4s', 0x45, 0, total, 0x1111, 0, 64, 17, 0,
                          bytes(int(p) for p in spoof_ip.split('.')),
                          bytes(int(p) for p in dst_ip.split('.')))
        iph = iph[:10] + struct.pack('>H', ip_checksum(iph)) + iph[12:]
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        results['v1_hdrincl'] = s.sendto(iph + udp, (dst_ip, 0))
        s.close()
    except OSError as e:
        results['v1_hdrincl'] = repr(e)

    # V2: IPPROTO_RAW + IP_HDRINCL
    try:
        payload = b'MODE-RAWPROTO'
        udp = struct.pack('>HHHH', spoof_port, dst_port, 8 + len(payload), 0) + payload
        total = 20 + len(udp)
        iph = struct.pack('>BBHHHBBH4s4s', 0x45, 0, total, 0x2222, 0, 64, 17, 0,
                          bytes(int(p) for p in spoof_ip.split('.')),
                          bytes(int(p) for p in dst_ip.split('.')))
        iph = iph[:10] + struct.pack('>H', ip_checksum(iph)) + iph[12:]
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, 255)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        results['v2_rawproto'] = s.sendto(iph + udp, (dst_ip, 0))
        s.close()
    except OSError as e:
        results['v2_rawproto'] = repr(e)

    # V3: IPPROTO_UDP without HDRINCL, bind to the spoofed source
    try:
        payload = b'MODE-BINDSRC'
        udp = struct.pack('>HHHH', spoof_port, dst_port, 8 + len(payload), 0) + payload
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
        s.bind((spoof_ip, spoof_port))
        results['v3_bindraw'] = s.sendto(udp, (dst_ip, dst_port))
        s.close()
    except OSError as e:
        results['v3_bindraw'] = repr(e)

    print(json.dumps(results))


if __name__ == '__main__':
    main()
