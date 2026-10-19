"""P36 E2 v2: fake relay with fresh dedupe keys + B-channel 1001 probe.

Sequence (all 127.0.0.1):
  t+0.5 after first a1 : a8 registration ack (key AA0001)
  t+2.5               : a3 add FAKE1 + FAKE2 (key AA0002)
  t+4.0               : 1001 query to loader B port (8576) -> expect 1002 back
  t+6.0               : a9 remove FAKE2 (key AA0004)
  t+8.5               : aa replace FAKE1 (key AA0005)
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p36_codec as codec  # noqa: E402

LAB = Path.home() / 'sgi-protocol-lab-20260915'
RT = json.loads((Path.home() / 'Library/Application Support/SGI-Wine/runtime.json').read_text())
FAKE1 = 0x0A0B0C0D
FAKE2 = 0x0A0B0C0E


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=40)
    ap.add_argument('--relay-port', type=int, default=24736)
    ap.add_argument('--local-port', type=int, default=4630)
    ap.add_argument('--b-port', type=int, default=8576)
    ap.add_argument('--virtual-ip', default='10.9.9.9')
    ap.add_argument('--client', default='p36_loader_client.py')
    args = ap.parse_args()

    ev = LAB / 'evidence' / ('p36-e2-controlforge-' + time.strftime('%Y%m%d-%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    relay_log = (ev / 'relay-log.jsonl').open('w', encoding='utf-8')

    def log(obj):
        obj = dict(obj, wall=round(time.time(), 3))
        relay_log.write(json.dumps(obj, ensure_ascii=False) + '\n')
        relay_log.flush()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', args.relay_port))
    sock.settimeout(0.2)

    a8 = codec.msg_a8(codec.ip_to_int(args.virtual_ip), args.local_port, 0, 0,
                      flag=1, key=0x36AA0001)
    a3 = codec.msg_a3([(FAKE1, 0x11111111, 0x22222222, 0x33333333, 0x44),
                       (FAKE2, 0xAAAA0001, 0xBBBB0002, 0xCCCC0003, 0x55)],
                      key=0x36AA0002)
    a9 = codec.msg_a9(FAKE2, key=0x36AA0004)
    game_port = args.local_port + 1          # our fake "game" receiver
    # redirect FAKE1 endpoint to our fake game socket (127.0.0.1:4631)
    aa_redirect = codec.msg_aa(FAKE1, 0x0100007F, 0x00001712, 0, key=0x36AA0006)
    # status '2' sets state so the loader sends to the state-1 endpoint
    set_state = codec.msg_2(FAKE1, 0)
    # instruction channel: make the loader deliver a '!' frame to FAKE1
    instr_v1 = codec.msg_1000(0x0D0C0B0A, 0x611E, FAKE1, 0x1712, b'X1000-V1', 0, 1)
    instr_v2 = codec.msg_1000(0x0D0C0B0A, 0x611E, FAKE1, 0x1712, b'X1000-V2', 0, 0)
    schedule = [
        {'name': 'a8', 'delay': 0.5, 'dest': 'A', 'bytes': a8},
        {'name': 'a3', 'delay': 2.5, 'dest': 'A', 'bytes': codec.msg_a3(
            [(FAKE1, 0x11111111, 0x22222222, 0x33333333, 0x44)], key=0x36AA0002)},
        {'name': 'aa-redirect', 'delay': 5.0, 'dest': 'A', 'bytes': aa_redirect},
        {'name': 'set-state-2', 'delay': 6.0, 'dest': 'A', 'bytes': set_state},
        {'name': 'instr-v1-b5=1', 'delay': 7.0, 'dest': 'B', 'bytes': instr_v1},
        {'name': 'instr-v2-b5=0', 'delay': 8.5, 'dest': 'B', 'bytes': instr_v2},
    ]
    b_port_state = {'port': None}
    client_out = ev / 'client-stdout.jsonl'

    def poll_globals():
        try:
            for line in client_out.read_text(encoding='utf-8').splitlines():
                if '"globals"' in line:
                    g = json.loads(line).get('globals', {})
                    if g.get('B_port'):
                        b_port_state['port'] = g['B_port']
                    if g.get('loader_base'):
                        b_port_state['base'] = g['loader_base']
        except (OSError, ValueError):
            pass
    game_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    game_rx.bind(('127.0.0.1', game_port))
    game_rx.settimeout(0)
    log({'kind': 'plan', 'seq': [{'name': s['name'], 'delay': s['delay'],
                                  'bytes': s['bytes'].hex()} for s in schedule]})

    env = dict(os.environ, WINEPREFIX=RT['prefix'], WINEDEBUG='-all',
               DYLD_FALLBACK_LIBRARY_PATH=RT['dependency_lib'])
    wine = [RT['wine'], str(LAB / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8']
    cfg = {'relay_ip': '127.0.0.1', 'relay_port': args.relay_port,
           'local_port': args.local_port, 'virtual_ip': args.virtual_ip,
           'game_id': 1001, 'user_id': 777001, 'username': 'p36tester',
           'token': 'p36token', 'seconds': args.seconds}
    (ev / 'client-config.json').write_text(json.dumps(cfg, indent=2))
    client = subprocess.Popen(wine + [str(LAB / args.client)], env=env,
                              stdin=subprocess.PIPE, stdout=open(ev / 'client-stdout.jsonl', 'w'),
                              stderr=open(ev / 'client-stderr.txt', 'w'), text=True)
    client.stdin.write(json.dumps(cfg))
    client.stdin.close()

    t1 = None
    peer = None
    pending = list(schedule)
    start_wall = time.time()
    while time.time() - start_wall < args.seconds + 20:
        if client.poll() is not None and not pending:
            break
        try:
            data, src = sock.recvfrom(4096)
        except socket.timeout:
            data = None
        if data:
            log({'kind': 'rx', 'from': list(src), 'length': len(data),
                 'first': data[0] if data else None, 'hex': data.hex()[:2000]})
            if data[0] == 0xA1 and t1 is None:
                t1 = time.time()
                peer = src
                log({'kind': 'first_a1', 'from': list(src)})
        try:
            gdata, gsrc = game_rx.recvfrom(4096)
            decoded = None
            if gdata and len(gdata) >= 10:
                mark = gdata[-10:-6]
                if mark == b'\xdd\xcc\xbb\xaa':
                    decoded = {'src_ip': '.'.join(str(b) for b in gdata[-6:-2]),
                               'src_port': int.from_bytes(gdata[-2:], 'big')}
            log({'kind': 'game_rx', 'from': list(gsrc), 'length': len(gdata),
                 'hex': gdata.hex()[:2000], 'trailer': decoded})
        except OSError:
            pass
        if t1 is None:
            continue
        now = time.time() - t1
        while pending and now >= pending[0]['delay']:
            s = pending.pop(0)
            if s['dest'] == 'lsof':
                try:
                    out = subprocess.run(['lsof', '-nP', '-iUDP'], capture_output=True,
                                         text=True, timeout=10).stdout
                    rows = [r for r in out.splitlines()
                            if ('wine' in r.lower() or 'python' in r.lower()
                                or 'sgi' in r.lower())]
                    (ev / 'lsof-udp.txt').write_text(out)
                    log({'kind': 'lsof', 'rows': rows})
                except Exception as e:
                    log({'kind': 'lsof_error', 'error': str(e)})
                continue
            if s['dest'] == 'B':
                deadline = time.time() + 6
                while b_port_state.get('port') is None and time.time() < deadline:
                    poll_globals()
                    time.sleep(0.1)
                if b_port_state.get('port') is None:
                    log({'kind': 'tx_skip', 'name': s['name'],
                         'reason': 'no_B_port_reported'})
                    continue
                dest = ('127.0.0.1', b_port_state['port'])
            else:
                dest = peer if s['dest'] == 'A' else s['dest']
            try:
                sock.sendto(s['bytes'], dest)
                log({'kind': 'tx', 'name': s['name'], 'to': list(dest),
                     'bytes': s['bytes'].hex()})
            except OSError as e:
                log({'kind': 'tx_error', 'name': s['name'], 'error': str(e)})
    try:
        client.terminate()
    except Exception:
        pass
    time.sleep(0.5)
    log({'kind': 'end', 'client_rc': client.poll(), 'remaining': [s['name'] for s in pending]})
    (ev / 'run.json').write_text(json.dumps(
        {'args': vars(args), 'client_rc': client.poll(), 'seen_a1': t1 is not None,
         'sent': [s['name'] for s in schedule if s not in pending]}, indent=2))
    print(str(ev))


if __name__ == '__main__':
    main()
