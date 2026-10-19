#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P39c3 offline bed: real NetHookLoader + sessionless reliable-submit probe.

Self-contained on 127.0.0.1 (no real relay, no game, no lobby):
  fake relay  <- a1 ->  a8 + a3 (fake host entry, endpoints 127.0.0.1:4631/4632)
                        + '2' state update
  wine parent (p39c2_loader_host) spawns the p39c3 probe child
  child fires ONE native reliable submit (0x4b60) to the fed target id
  watcher: fake relay + two "game" sockets + child log

The question this bed answers: what (if anything) does a *sessionless*
Koeinm's reliable submit emit, and of which wire class ('!' 0x21 / '0x22'
UDT / a4-wrapped / nothing)? The emission itself is the finding - the bed
reports it instead of asserting a hoped-for outcome.

Artifacts under LAB/evidence/p39c3-bed-<ts>/.
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

LAB = Path.home() / 'sgi-protocol-lab-20260915'
OWN_IP = '10.9.9.9'
OWN_ID = codec.ip_to_id(OWN_IP)
HOST_IP = '10.123.123.1'
HOST_ID = codec.ip_to_id(HOST_IP)
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


def classify_uplink(payload):
    """Classify a loader uplink datagram (best effort, raw kept elsewhere)."""
    if not payload:
        return 'empty'
    if payload[0] == 0xA4 and len(payload) >= 15:
        inner = payload[15:]
        kind = 'a4+?'
        if inner[:1] == b'\x21':
            kind = 'a4+\'!\'(0x21)'
        elif inner[:1] == b'\x22':
            kind = 'a4+0x22(UDT)'
        return '%s src=%s dst=%s innerlen=%d' % (
            kind, payload[5:9].hex(), payload[11:15].hex(), len(inner))
    if payload[0] == 0x21:
        return '\'!\'(0x21) direct'
    if payload[0] == 0x22:
        return '0x22(UDT) direct'
    return 'first_byte=%02x' % payload[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--relay-port', type=int, default=24741)
    ap.add_argument('--seconds', type=float, default=70)
    args = ap.parse_args()
    ev = LAB / 'evidence' / ('p39c3-bed-' + time.strftime('%Y%m%d-%H%M%S'))
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

    gate = {'target': HOST_ID, 'note': 'p39c3 bed: D9 harmless body'}
    (ev / 'submit-gate.json').write_text(json.dumps(gate), encoding='utf-8')

    wine, env = wine_paths()
    env = dict(env)
    env['P2_CHILD_SCRIPT'] = 'p39c3_reliable_submit_probe.py'
    env['P2_CHILD_ARGS_JSON'] = json.dumps([
        '--log', zpath(ev / 'child.jsonl'),
        '--stop-file', zpath(ev / 'stop-child'),
        '--submit-gate', zpath(ev / 'submit-gate.json'),
        '--submit-delay', '8'])
    env['P2_CHILD_STDERR'] = zpath(ev / 'child.stderr')
    env['P39C2_CTX_FILE'] = zpath(ev / 'ctx.json')
    env['P39C2_TABLE_LOG'] = zpath(ev / 'table.jsonl')
    cfg = {'username': 'p39c3bed', 'virtual_ip': OWN_IP, 'server': '127.0.0.1',
           'port': args.relay_port, 'game_id': 1001, 'user_id': 777002,
           'token': 'p39c3bedtoken', 'search_target': HOST_IP,
           'session_name': 'P39C3BED', 'hold_seconds': 180}
    (ev / 'config.json').write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    parent = subprocess.Popen(
        [wine, str(LAB / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8',
         str(LAB / 'p39c2_loader_host.py')],
        stdin=subprocess.PIPE, stdout=(ev / 'host.stdout').open('w'),
        stderr=(ev / 'host.stderr').open('w'), text=True, env=env,
        start_new_session=True)
    # NOTE: child log path is decided by this bed and passed via P2_CHILD_ARGS
    # inside the parent invocation below - add it now for clarity.
    parent.stdin.write(json.dumps(cfg))
    parent.stdin.close()
    log({'k': 'parent_spawn', 'pid': parent.pid, 'relay_port': args.relay_port,
         'gate': gate})

    state = {'t1': None, 'peer': None, 'sched': [], 'key': 0x39C3B000,
             'uplinks': [], 'game_rx': [], 'other': 0}
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            try:
                data, src = relay.recvfrom(4096)
            except socket.timeout:
                data = None
            if data:
                kind = classify_uplink(data)
                rec = {'k': 'relay_rx', 'from': list(src), 'len': len(data),
                       'class': kind, 'hex': data.hex()[:400]}
                log(rec)
                if data[0] == 0xA4:
                    state['uplinks'].append(rec)
                if data[0] == 0xA1 and state['t1'] is None:
                    state['t1'] = time.time()
                    state['peer'] = src
                    state['sched'] = [(0.5, 'a8'), (2.0, 'a3'), (2.5, 'two')]
                    log({'k': 'first_a1', 'from': list(src)})
            for name, gsock, port in (('ep_a', g1, EP_A), ('ep_b', g2, EP_B)):
                try:
                    gdata, gsrc = gsock.recvfrom(4096)
                except OSError:
                    gdata = None
                if gdata:
                    rec = {'k': 'game_rx', 'port': port, 'from': list(gsrc),
                           'len': len(gdata), 'class': classify_uplink(gdata),
                           'hex': gdata.hex()}
                    log(rec)
                    state['game_rx'].append(rec)
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
                else:
                    msg = codec.msg_2(HOST_ID, 0)
                relay.sendto(msg, state['peer'])
                log({'k': 'relay_tx', 'what': what, 'hex': msg.hex()})
            if state['t1'] and now > 30 and not state.get('late_note'):
                state['late_note'] = True
                log({'k': 'window_note', 'note': '30s after first a1; submit ~8s after child start'})
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

    child_events = []
    child_log = ev / 'child.jsonl'
    submit_wall = None
    end_wall = time.time()
    try:
        for line in child_log.read_text(encoding='utf-8').splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('ev') == 'submit_call_return':
                submit_wall = e.get('wall')
            if e.get('ev') in ('submit_pre', 'submit_get_or_self',
                               'submit_get_or_self_exception', 'submit_call_return',
                               'submit_call_exception', 'submit_post', 'closed',
                               'relay_address', 'start_return'):
                child_events.append(e)
    except OSError:
        pass
    summary = {
        'uplinks_after_start': state['uplinks'],
        'game_rx': state['game_rx'],
        'child_events': child_events,
        'seconds': args.seconds,
        'submit_wall': submit_wall,
        'end_wall': end_wall,
        'post_submit_observed_seconds': (round(end_wall - submit_wall, 2)
                                         if submit_wall else None),
        'observed_endpoints': ['127.0.0.1:24741(relay)', '127.0.0.1:4631', '127.0.0.1:4632'],
        'observation_scope_note': ('UDP receives at the three monitored loopback '
                                   'endpoints only; no full packet capture; '
                                   'delayed emission beyond this window not excluded'),
    }
    (ev / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    log({'k': 'end', 'uplink_count': len(state['uplinks']),
         'game_rx_count': len(state['game_rx'])})
    logf.close()
    print(json.dumps({'evidence': str(ev),
                      'uplinks': len(state['uplinks']),
                      'game_rx': len(state['game_rx'])}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
