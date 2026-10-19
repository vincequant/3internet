#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P41 offline bed: can the REAL loader emit the leave '!' (and the a4 wrapper?)
from the P41 1000 instruction?  (real NetHookLoader under Wine + fake relay)

Zero real-network contact. Sequence mirrors p39c2_bed_test.py:
  register -> feed fake host entry (a8/a3/aa/'2') -> send instructions to B port
  - instr #1 (broadcast, addr2=ffffffff)  <- THE P41 LEAVE FRAME
  - instr #2 (unicast control, addr2=HOST_ID)
Logs EVERY datagram at the fake relay and both game endpoints; compares against
p41_leave_frame expected bytes.

Artifacts: LAB/evidence/p41-bed-<ts>/ (bed.jsonl, ctx.json, table.jsonl,
host stdout/stderr, summary.json).
"""
import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p39c2_frame as codec  # noqa: E402
import p41_leave_frame as p41  # noqa: E402

LAB = Path.home() / 'sgi-protocol-lab-20260915'
OWN_IP = '10.9.9.9'
OWN_ID = codec.ip_to_id(OWN_IP)
HOST_IP = '10.123.123.1'
HOST_ID = codec.ip_to_id(HOST_IP)
HOST_PORT = 7777
TAG2 = 0xD0C0
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
    ev = LAB / 'evidence' / ('p41-bed-' + time.strftime('%Y%m%d-%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    logf = (ev / 'bed.jsonl').open('w', encoding='utf-8')

    def log(obj):
        obj = dict(obj, wall=round(time.time(), 3))
        logf.write(json.dumps(obj, ensure_ascii=False) + '\n')
        logf.flush()

    expected_bang = p41.build_leave_payload(OWN_ID, TAG2)
    expected_wrapper = p41.build_leave_wire(OWN_ID, TAG2)
    instr_bc = p41.build_leave_instr1000(OWN_ID, TAG2)
    instr_uc = p41.build_leave_instr1000(OWN_ID, TAG2, target=HOST_ID,
                                         deliver_port=HOST_PORT,
                                         flag4=0, flag5=0)
    ctrl_bang = p41.build_leave_payload(OWN_ID, TAG2, target=HOST_ID,
                                        deliver_port=HOST_PORT)

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
    cfg = {'username': 'p41bed', 'virtual_ip': OWN_IP, 'server': '127.0.0.1',
           'port': args.relay_port, 'game_id': 1004, 'user_id': 777004,
           'token': 'p41bedtoken', 'search_target': HOST_IP,
           'session_name': 'P41BED', 'hold_seconds': 90}
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

    state = {'t1': None, 'peer': None, 'sched': [], 'key': 0x41B00000,
             'bc_sent': False, 'uc_sent': False, 'bc_wall': None, 'uc_wall': None,
             'relay_rx': [], 'game_rx': []}
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            try:
                data, src = relay.recvfrom(4096)
            except socket.timeout:
                data = None
            if data:
                rec = {'port': 'relay', 'from': list(src), 'len': len(data),
                       'hex': data.hex()}
                if data == expected_wrapper:
                    rec['match'] = 'P41_LEAVE_WRAPPER'
                elif data == expected_bang:
                    rec['match'] = 'P41_LEAVE_BANG'
                state['relay_rx'].append(rec)
                log(dict(rec, k='relay_rx'))
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
                    rec = {'port': port, 'from': list(gsrc), 'len': len(gdata),
                           'hex': gdata.hex()}
                    if gdata == expected_bang:
                        rec['match'] = 'P41_LEAVE_BANG'
                    elif gdata == ctrl_bang:
                        rec['match'] = 'P41_CONTROL_BANG'
                    elif gdata == expected_wrapper:
                        rec['match'] = 'P41_LEAVE_WRAPPER'
                    state['game_rx'].append(rec)
                    log(dict(rec, k='game_rx'))
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
                                         '127.0.0.1', EP_B, 1)], key=state['key'])
                elif what == 'aa':
                    msg = codec.msg_aa(HOST_ID, '127.0.0.1', EP_A,
                                       '127.0.0.1', EP_B, 1, key=state['key'])
                else:
                    msg = codec.msg_2(HOST_ID, 0)
                relay.sendto(msg, state['peer'])
                log({'k': 'relay_tx', 'what': what, 'hex': msg.hex()})
            if not state['bc_sent'] and now > 3.5:
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
                    rc = tx.sendto(instr_bc, ('127.0.0.1', ctx['b_port']))
                    tx.close()
                    state['bc_sent'] = True
                    state['bc_wall'] = time.time()
                    log({'k': 'instr_bc_tx', 'rc': rc, 'dst': ['127.0.0.1', ctx['b_port']],
                         'hex': instr_bc.hex(), 'expected_bang': expected_bang.hex()})
            if state['bc_sent'] and not state['uc_sent'] and time.time() - state['bc_wall'] > 3.0:
                tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                rc = tx.sendto(instr_uc, ('127.0.0.1', state['ctx']['b_port']))
                tx.close()
                state['uc_sent'] = True
                state['uc_wall'] = time.time()
                log({'k': 'instr_uc_tx', 'rc': rc, 'hex': instr_uc.hex(),
                     'expected_bang': ctrl_bang.hex()})
            if state['uc_sent'] and time.time() - state['uc_wall'] > 5.0:
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

    def seen(which, match):
        return [r for r in state[which] if r.get('match') == match]

    checks = {
        'bc_bang_seen_anywhere': bool(seen('game_rx', 'P41_LEAVE_BANG')
                                      or seen('relay_rx', 'P41_LEAVE_BANG')),
        'bc_bang_at_game': bool(seen('game_rx', 'P41_LEAVE_BANG')),
        'bc_wrapper_at_relay': bool(seen('relay_rx', 'P41_LEAVE_WRAPPER')),
        'uc_control_bang_seen': bool(seen('game_rx', 'P41_CONTROL_BANG')
                                     or seen('relay_rx', 'P41_CONTROL_BANG')),
        'relay_rx_count': len(state['relay_rx']),
        'game_rx_count': len(state['game_rx']),
    }
    summary = {
        'checks': checks,
        'expected_bang_hex': expected_bang.hex(),
        'expected_wrapper_hex': expected_wrapper.hex(),
        'instr_bc_hex': instr_bc.hex(),
        'instr_uc_hex': instr_uc.hex(),
        'ctrl_bang_hex': ctrl_bang.hex(),
        'relay_rx': state['relay_rx'],
        'game_rx': state['game_rx'],
        'ctx': state.get('ctx'),
        'seconds': args.seconds,
    }
    (ev / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    log({'k': 'end', 'checks': checks})
    logf.close()
    print(json.dumps({'evidence': str(ev), 'checks': checks}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
