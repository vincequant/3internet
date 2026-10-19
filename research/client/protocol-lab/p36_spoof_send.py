"""P36: send ONE raw UDP packet with a spoofed source (root on macOS).

Usage: sudo /usr/bin/python3 p36_spoof_send.py --spoof-ip A --spoof-port P \
       --dst-ip B --dst-port Q [--payload HEX|text]
"""
import argparse
import json
import socket
import struct


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
    iph = iph[:10] + struct.pack('>H', ip_checksum(iph)) + iph[12:]
    return iph + udp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spoof-ip', required=True)
    ap.add_argument('--spoof-port', type=int, default=29100)
    ap.add_argument('--dst-ip', required=True)
    ap.add_argument('--dst-port', type=int, required=True)
    ap.add_argument('--payload', default='P36-WAN-SIM')
    ap.add_argument('--payload-hex')
    ap.add_argument('--bind-if', help='force outgoing interface (macOS IP_BOUND_IF)')
    args = ap.parse_args()
    payload = bytes.fromhex(args.payload_hex) if args.payload_hex else args.payload.encode()
    pkt = build(args.spoof_ip, args.dst_ip, args.spoof_port, args.dst_port, payload)
    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    if args.bind_if:
        idx = socket.if_nametoindex(args.bind_if)
        s.setsockopt(socket.IPPROTO_IP, 25, struct.pack('I', idx))  # macOS IP_BOUND_IF
    sent = s.sendto(pkt, (args.dst_ip, 0))
    s.close()
    print(json.dumps({'sent': sent, 'from': [args.spoof_ip, args.spoof_port],
                      'to': [args.dst_ip, args.dst_port], 'bind_if': args.bind_if,
                      'payload_hex': payload.hex()}))


if __name__ == '__main__':
    main()
