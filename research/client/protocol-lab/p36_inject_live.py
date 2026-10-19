"""P36 live injection: send ONE forged '!' frame to a local NetHook loader.

Usage:
  python3 p36_inject_live.py --payload-hex 540a78483a0000000000 \
      [--dest-port 4577] [--deliver-port 7777] [--src-ip 10.11.12.13]
      [--src-port 7777] [--dry-run]
"""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p36_codec as codec  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dest-ip', default='127.0.0.1')
    ap.add_argument('--dest-port', type=int, default=4577)
    ap.add_argument('--deliver-port', type=int, default=7777)
    ap.add_argument('--src-ip', default='10.11.12.13')
    ap.add_argument('--src-port', type=int, default=7777)
    ap.add_argument('--payload-hex', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    payload = bytes.fromhex(args.payload_hex)
    frame = codec.bang_encode(payload, args.src_ip, args.src_port, args.deliver_port)
    result = {'dest': [args.dest_ip, args.dest_port], 'deliver_port': args.deliver_port,
              'src': [args.src_ip, args.src_port], 'payload_len': len(payload),
              'frame_hex': frame.hex(), 'crc': frame[1], 'dry_run': args.dry_run,
              'wall': round(time.time(), 3)}
    if not args.dry_run:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        result['sent'] = s.sendto(frame, (args.dest_ip, args.dest_port))
        s.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
