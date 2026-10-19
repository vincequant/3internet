"""P36: can wine (non-root) create a raw socket for source spoofing? (probe only)"""
import json
import socket
import struct
import sys

result = {'wine_python': sys.version}
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
    result['raw_create'] = 'ok'
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        result['ip_hdrincl'] = 'ok'
    except OSError as e:
        result['ip_hdrincl'] = repr(e)
    # craft minimal IP+UDP datagram: src 10.255.255.254:9999 -> 127.0.0.1:4630
    payload = b'RAW-PROBE'
    udp = struct.pack('>HHHH', 9999, 4630, 8 + len(payload), 0) + payload
    total = 20 + len(udp)
    iph = struct.pack('>BBHHHBBH4s4s', 0x45, 0, total, 1, 0, 64, 17, 0,
                      bytes([10, 255, 255, 254]), bytes([127, 0, 0, 1]))
    try:
        n = s.sendto(iph + udp, ('127.0.0.1', 0))
        result['raw_send'] = n
    except OSError as e:
        result['raw_send'] = repr(e)
    s.close()
except OSError as e:
    result['raw_create'] = repr(e)
print(json.dumps(result), flush=True)
