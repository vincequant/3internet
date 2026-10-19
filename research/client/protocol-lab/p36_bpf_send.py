"""P36: inject a spoofed-source UDP packet via /dev/bpf (raw Ethernet write, root).

Usage: sudo /usr/bin/python3 p36_bpf_send.py --if en0 \
         --src-ip 36.151.147.251 --src-port 29100 \
         --dst-ip 192.168.188.129 --dst-port 46999 --payload "TEXT"
"""
import argparse
import fcntl
import json
import re
import struct
import subprocess

BIOCSBLEN = 0xC0044266
BIOCSETIF = 0x8020426C
BIOCIMMEDIATE = 0x80044270
BIOCSHDRCMPLT = 0x80044275


def ioctl(fd, req, arg):
    return fcntl.ioctl(fd, req, arg)


def ip_checksum(hdr: bytes) -> int:
    if len(hdr) % 2:
        hdr += b'\x00'
    total = 0
    for i in range(0, len(hdr), 2):
        total += (hdr[i] << 8) + hdr[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def mac_bytes(s):
    return bytes(int(x, 16) for x in s.split(':'))


def if_mac(name):
    out = subprocess.run(['ifconfig', name], capture_output=True, text=True).stdout
    m = re.search(r'ether ([0-9a-f:]{17})', out)
    return m.group(1) if m else None


def arp_mac(ip):
    out = subprocess.run(['arp', '-n', ip], capture_output=True, text=True).stdout
    m = re.search(r'([0-9a-f]{1,2}(:[0-9a-f]{1,2}){5})', out)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--if', dest='iface', default='en0')
    ap.add_argument('--src-ip', required=True)
    ap.add_argument('--src-port', type=int, default=29100)
    ap.add_argument('--dst-ip', required=True)
    ap.add_argument('--dst-port', type=int, required=True)
    ap.add_argument('--dst-mac', help='override destination MAC')
    ap.add_argument('--payload', default='P36-BPF')
    ap.add_argument('--payload-hex')
    args = ap.parse_args()

    src_mac = if_mac(args.iface)
    dst_mac = args.dst_mac or arp_mac(args.dst_ip)
    result = {'if': args.iface, 'src_mac': src_mac, 'dst_mac': dst_mac}
    if not src_mac or not dst_mac:
        result['error'] = 'missing_mac'
        print(json.dumps(result))
        return 1

    payload = bytes.fromhex(args.payload_hex) if args.payload_hex else args.payload.encode()
    udp = struct.pack('>HHHH', args.src_port, args.dst_port, 8 + len(payload), 0) + payload
    total = 20 + len(udp)
    iph = struct.pack('>BBHHHBBH4s4s', 0x45, 0, total, 0x3333, 0, 64, 17, 0,
                      bytes(int(p) for p in args.src_ip.split('.')),
                      bytes(int(p) for p in args.dst_ip.split('.')))
    iph = iph[:10] + struct.pack('>H', ip_checksum(iph)) + iph[12:]
    frame = mac_bytes(dst_mac) + mac_bytes(src_mac) + b'\x08\x00' + iph + udp

    fd = None
    for n in range(4):
        try:
            fd = open('/dev/bpf%d' % n, 'r+b', buffering=0)
            break
        except OSError:
            continue
    if fd is None:
        result['error'] = 'no_bpf_device'
        print(json.dumps(result))
        return 1
    try:
        ioctl(fd, BIOCSBLEN, struct.pack('I', 4096))
        ioctl(fd, BIOCSETIF, struct.pack('16s', args.iface.encode()))
        ioctl(fd, BIOCIMMEDIATE, struct.pack('I', 1))
        ioctl(fd, BIOCSHDRCMPLT, struct.pack('I', 1))
        written = fd.write(frame)
        result['written'] = written
    finally:
        fd.close()
    result['frame_len'] = len(frame)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
