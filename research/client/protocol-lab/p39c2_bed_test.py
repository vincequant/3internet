#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P39c2 offline bed: real NetHookLoader under Wine + fake relay on 127.0.0.1.

Proves, with zero real-network contact (no real relay, no game, no lobby):

  - p39c2_loader_host.py StartServer registers with a fake relay (a1 seen);
  - after the fake relay feeds a8 + a3 + aa + '2' for one fake host entry,
    the p39c2_frame.instr1000 single-shot instruction sent to the loader's
    B port (from the Mac side, exactly as the orchestrator will do) makes the
    REAL loader emit exactly ONE wire '!' datagram to the fed endpoint with:
      [2..5]  = BE32(target id)        (addr2 wire bytes, verbatim)
      [6..7]  = BE16(target port)      (port2 wire bytes, verbatim)
      [8..11] = BE32(own id)           (addr1 wire bytes, verbatim)
      [12..13]= BE16(own port)         (port1 wire bytes, verbatim)
      payload = the exact 18-byte step-1 envelope frame.
  - no second datagram follows.

Artifacts: LAB/evidence/p39c2-bed-<ts>/ (bed.jsonl, ctx.json, table.jsonl,
host stdout/stderr, summary.json).
"""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p39c2_frame as codec  # noqa: E402

LAB = Path.home() / 'sgi-protocol-lab-20260915'
OWN_IP = '10.9.9.9'
OWN_ID = codec.ip_to_id(OWN_IP)
HOST_IP = '10.123.123.1'
HOST_ID = codec.ip_to_id(HOST_IP)
HOST_PORT = 7777
EP_A = 4631
EP_B = 4632


def zpath(path):
    return 'Z:' + str(path).replace('/', '\\')


def wine_paths():
    sys.path.insert(0, str(Path.home() / 'Library/Application Support/SGI-Room-Monitor/opt'))
    from sgi_room_monitor.provision import default_paths, wine_env
    paths = default_paths()
    return paths['wine'], wine_env(
        paths['wine'],
        str(Path.home() / 'Library/Application Support/SGI-Wine/prefix-monitor'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--relay-port', type=int, default=24739)
    ap.add_argument('--seconds', type=float, default=45)
    args = ap.parse_args()
    ev = LAB / 'evidence' / ('p39c2-bed-' + time.strftime('%Y%m%d-%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    logf = (ev / 'bed.jsonl').open('w', encoding='utf-8')

    def log(obj):
        obj = dict(obj, wall=round(time.time(), 3))
        logf.write(json.dumps(obj, ensure_ascii=False) + '\n')
        logf.flush()

    relay = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    relay.bind(('127.0.0.1', args.relay_port))
    relay.settimeout(0.1)
    g1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    g1.bind(('127.0.0.1', EP_A))
    g2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    g2.bind(('127.0.0.1', EP_B))
    for g in (g1, g2):
        g.setblocking(False)

    wine, env = wine_paths()
    env = dict(env)
    env['P2_CHILD_SCRIPT'] = 'p39c2_bed_child.py'
    env['P2_CHILD_ARGS_JSON'] = '[]'
    env['P2_CHILD_STDERR'] = zpath(ev / 'child.stderr')
    env['P39C2_CTX_FILE'] = zpath(ev / 'ctx.json')
    env['P39C2_TABLE_LOG'] = zpath(ev / 'table.jsonl')
    cfg = {'username': 'p39c2bed', 'virtual_ip': OWN_IP, 'server': '127.0.0.1',
           'port': args.relay_port, 'game_id': 1001, 'user_id': 777001,
           'token': 'p39c2bedtoken', 'search_target': HOST_IP,
           'session_name': 'P39C2BED', 'hold_seconds': 60}
    (ev / 'config.json').write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    parent = subprocess.Popen(
        [wine, str(LAB / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8',
         str(LAB / 'p39c2_loader_host.py')],
        stdin=subprocess.PIPE, stdout=(ev / 'host.stdout').open('w'),
        stderr=(ev / 'host.stderr').open('w'), text=True, env=env,
        start_new_session=True)
    parent.stdin.write(json.dumps(cfg))
    parent.stdin.close()
    log({'k': 'parent_spawn', 'pid': parent.pid, 'relay_port': args.relay_port})

    frame = codec.step1_frame(OWN_ID)
    instr = codec.instr1000(OWN_ID, HOST_PORT, HOST_ID, HOST_PORT, frame)
    state = {'t1': None, 'peer': None, 'sched': [], 'key': 0x39C20000,
             'instr_sent': False, 'instr_wall': None, 'rx': [], 'other_rx': 0,
             'ctx': None}
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            try:
                data, src = relay.recvfrom(4096)
            except socket.timeout:
                data = None
            if data:
                log({'k': 'relay_rx', 'from': list(src), 'len': len(data),
                     'first': data[0], 'hex': data.hex()[:400]})
                if data[0] == 0xA4 and state['instr_sent']:
                    state.setdefault('a4_seen', []).append(data)
                if data[0] == 0xA1 and state['t1'] is None:
                    state['t1'] = time.time()
                    state['peer'] = src
                    state['sched'] = [(0.5, 'a8'), (2.0, 'a3'), (2.5, 'aa'),
                                      (3.0, 'two')]
                    log({'k': 'first_a1', 'from': list(src)})
            for name, gsock, port in (('ep_a', g1, EP_A), ('ep_b', g2, EP_B)):
                try:
                    gdata, gsrc = gsock.recvfrom(4096)
                except OSError:
                    gdata = None
                if gdata:
                    parsed = codec.bang_parse(gdata)
                    rec = {'k': 'game_rx', 'port': port, 'from': list(gsrc),
                           'len': len(gdata), 'hex': gdata.hex(),
                           'parsed': parsed}
                    log(rec)
                    if parsed.get('payload_hex') == frame.hex():
                        state['rx'].append(rec)
                    else:
                        state['other_rx'] += 1
            if state['t1'] is None:
                continue
            now = time.time() - state['t1']
            while state['sched'] and now >= state['sched'][0][0]:
                _, what = state['sched'].pop(0)
                state['key'] += 1
                if what == 'a8':
                    msg = codec.msg_a8(OWN_ID, '127.0.0.1', 4633, '127.0.0.1',
                                       4634, 1, key=state['key'])
                elif what == 'a3':
                    msg = codec.msg_a3([(HOST_ID, '127.0.0.1', EP_A,
                                         '127.0.0.1', EP_B, 1)],
                                       key=state['key'])
                elif what == 'aa':
                    msg = codec.msg_aa(HOST_ID, '127.0.0.1', EP_A,
                                       '127.0.0.1', EP_B, 1, key=state['key'])
                else:
                    msg = codec.msg_2(HOST_ID, 0)
                relay.sendto(msg, state['peer'])
                log({'k': 'relay_tx', 'what': what, 'hex': msg.hex()})
            if not state['instr_sent'] and now > 3.5:
                ctx = None
                try:
                    ctx = json.loads((ev / 'ctx.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    ctx = None
                if ctx and ctx.get('b_port'):
                    state['ctx'] = ctx
                    if not ctx.get('registered'):
                        log({'k': 'no_registration', 'ctx': ctx})
                        break
                    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    rc = tx.sendto(instr, ('127.0.0.1', ctx['b_port']))
                    tx.close()
                    state['instr_sent'] = True
                    state['instr_wall'] = time.time()
                    log({'k': 'instruction_tx', 'rc': rc, 'dst': ['127.0.0.1', ctx['b_port']],
                         'hex': instr.hex(), 'frame_hex': frame.hex()})
            if state['instr_sent'] and time.time() - state['instr_wall'] > 5:
                break
    finally:
        try:
            os.killpg(os.getpgid(parent.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            parent.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(parent.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        for s in (relay, g1, g2):
            s.close()

    checks, rx0 = {}, (state['rx'][0]['parsed'] if state['rx'] else {})
    checks['a1_seen'] = state['t1'] is not None
    checks['instruction_sent'] = state['instr_sent']
    checks['exactly_one_frame_delivered'] = len(state['rx']) == 1
    checks['crc_ok'] = bool(rx0.get('crc_ok'))
    checks['deliver_port_is_target_port'] = rx0.get('deliver_port') == HOST_PORT
    checks['vip_bytes_are_target_id'] = rx0.get('vip_id_hex') == HOST_ID.to_bytes(4, 'big').hex()
    checks['src_id_is_own_id'] = rx0.get('src_id') == OWN_ID
    checks['src_port_is_own_port'] = rx0.get('src_port') == HOST_PORT
    checks['payload_is_step1_frame'] = rx0.get('payload_hex') == frame.hex()
    checks['no_trailer'] = rx0.get('trailer_hex', '') == ''
    passed = all(checks.values())
    summary = {'pass': passed, 'checks': checks,
               'instruction_hex': instr.hex(),
               'instruction_sha256': codec.sha256_hex(instr),
               'frame_hex': frame.hex(), 'frame_sha256': codec.sha256_hex(frame),
               'rx_count': len(state['rx']), 'other_rx': state['other_rx'],
               'rx': state['rx'], 'ctx': state['ctx'],
               'a4_seen': [x.hex() for x in state.get('a4_seen', [])],
               'seconds': args.seconds}
    (ev / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    log({'k': 'end', 'pass': passed, 'checks': checks})
    logf.close()
    print(json.dumps({'evidence': str(ev), 'pass': passed, 'checks': checks},
                     ensure_ascii=True))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
