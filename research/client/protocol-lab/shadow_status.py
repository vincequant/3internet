#!/usr/bin/env python3
"""Fengye live status writer (raw inputs for the intel hub).

Runs inside the shadow prefix (wine py32) and rewrites <session>/status.json
every few seconds. READ-ONLY: no sends, no memory writes, no game action.

The hub is the only place that turns these raw numbers into player-facing
words; this file stays mechanical so it can be verified field by field.
"""
import argparse
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path


def read_u32(read, addr):
    raw = read(addr, 4)
    return struct.unpack('<I', raw)[0] if raw else None


def last_packet_wall(packets_path):
    try:
        with open(packets_path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 8192))
            tail = handle.read().decode('utf-8', 'replace').splitlines()
        for line in reversed(tail):
            line = line.strip()
            if not line.startswith('{'):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            wall = row.get('wall')
            if isinstance(wall, (int, float)):
                return float(wall)
    except OSError:
        return None
    return None


def receipt_age(path):
    try:
        return round(time.time() - os.path.getmtime(path), 1)
    except OSError:
        return None


def receipt_state(path):
    """SHG5 rows: (round, event, tick, f6bc, G68). event 0=spawn 2=done 9=fault."""
    out = {'rows': 0, 'rounds': 0, 'last_event': None, 'last_tick': None, 'faults': 0}
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return out
    rows = []
    off = 0
    while off + 24 <= len(raw):
        magic, index, event, tick, _f6, _g68 = struct.unpack_from('<IIIIII', raw, off)
        if magic != 0x35474853:
            off += 4
            continue
        rows.append((index, event, tick))
        off += 24
    if not rows:
        return out
    out['rows'] = len(rows)
    out['rounds'] = max(r[0] for r in rows)
    out['last_event'] = rows[-1][1]
    out['last_tick'] = rows[-1][2]
    out['faults'] = sum(1 for r in rows if r[1] == 9)
    return out


def world_counts(samples_dir, max_age=180.0):
    try:
        with open(os.path.join(samples_dir, 'index.jsonl'), 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 8192))
            tail = handle.read().decode('utf-8', 'replace').splitlines()
        for line in reversed(tail):
            line = line.strip()
            if not line.startswith('{'):
                continue
            row = json.loads(line)
            counts = row.get('counts') or {}
            wall = row.get('wall')
            if not isinstance(wall, (int, float)):
                continue
            if time.time() - wall > max_age:
                return None
            return {'units': counts.get('field_units'), 'cities': counts.get('cities_and_barriers'),
                    'generals': counts.get('generals'), 'lords': counts.get('lords'),
                    'at': wall}
    except (OSError, ValueError):
        return None
    return None


def json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True, help='hub session directory (holds state.json)')
    ap.add_argument('--shadow', default=None, help='shadow dir (markers/receipts)')
    ap.add_argument('--samples', default=None, help='sampler output dir')
    ap.add_argument('--bridge', default=os.environ.get(
        'SGI_BRIDGE_Z', r'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\bridge'))
    ap.add_argument('--interval', type=float, default=2.0)
    ap.add_argument('--duration', type=float, default=0.0, help='0 = run forever')
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector
    import p53_unit_data as unit_data

    session = Path(args.session)
    output = session / 'status.json'
    shadow = Path(args.shadow) if args.shadow else session
    started = time.time()
    while True:
        block = {'schema': 'fengye-status-1', 'wall': round(time.time(), 3)}
        try:
            k = _win()
            pid = find_sanpk(k)
            block['pid'] = pid
            if not pid:
                block['present'] = False
            else:
                block['present'] = True
                col = Collector(pid)
                try:
                    col.bind()
                    core = int(col.core)
                finally:
                    col.close()
                # 0x0410 = QUERY_INFORMATION | VM_READ: EnumProcessModulesEx needs query rights
                h = k.OpenProcess(0x0410, False, pid)

                def read(addr, size):
                    import ctypes as c
                    buf = c.create_string_buffer(size)
                    got = c.c_size_t()
                    if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, size, c.byref(got)) \
                            or got.value != size:
                        return None
                    return buf.raw

                # network object (Koeinm instance) for link counters
                import ctypes as c
                psapi = c.WinDLL('psapi')
                psapi.EnumProcessModulesEx.argtypes = [c.c_void_p, c.POINTER(c.c_void_p),
                                                       c.c_uint32, c.POINTER(c.c_uint32), c.c_uint32]
                psapi.GetModuleFileNameExW.argtypes = [c.c_void_p, c.c_void_p, c.c_wchar_p, c.c_uint32]
                modules = (c.c_void_p * 512)()
                needed = c.c_uint32()
                base = None
                if psapi.EnumProcessModulesEx(h, modules, c.sizeof(modules), c.byref(needed), 3):
                    for item in modules[:needed.value // c.sizeof(c.c_void_p)]:
                        name = c.create_unicode_buffer(1024)
                        psapi.GetModuleFileNameExW(h, item, name, len(name))
                        if name.value.lower().endswith('\\koeinm.dll'):
                            base = item
                net = (base + 0x12170) if base else 0
                block['link'] = {
                    'connected': bool(read_u32(read, net + 0x84a8) not in (None,)),
                    'sync': read_u32(read, net + 0x84a8),
                    'tx': read_u32(read, net + 0x8440),
                    'rx_backlog': read_u32(read, net + 0x84b4),
                }
                try:
                    ctx = unit_data.context(read)
                    block['scene'] = {'in_map': ctx['mode'] == 3, 'mode': ctx['mode'],
                                      'phase': ctx['phase']}
                except Exception as error:
                    block['scene'] = {'in_map': None, 'error': type(error).__name__}
                slot = read_u32(read, core + 0x6C0)
                slot_force = None
                if isinstance(slot, int) and 0 <= slot <= 7:
                    slot_force = read_u32(read, core + 0x4A + slot * 0x87)
                block['seat'] = {'slot': slot, 'force': slot_force}
        except Exception as error:
            block['probe_error'] = type(error).__name__

        recorder = json_file(session / 'state.json') or {}
        last = last_packet_wall(session / 'packets.jsonl')
        block['rx'] = {'received': recorder.get('received'),
                       'last_wall': last,
                       'last_age': (round(time.time() - last, 1) if last else None)}
        block['hide'] = json_file(shadow / 'shadow_hidden.json')
        block['godview'] = json_file(shadow / 'shadow_godview.json')
        receipt_path = shadow / 'shadow_round_c_receipt.bin'
        block['driver'] = receipt_state(receipt_path)
        block['driver']['age'] = receipt_age(receipt_path)
        resident = json_file(shadow / 'inject-state-resident.json') or {}
        block['driver']['hooks'] = resident.get('schema') == 'p51-shadow-resident-1'
        block['driver']['started'] = bool(resident.get('started_wall'))
        if args.samples:
            block['world'] = world_counts(args.samples)
        try:
            free = shutil.disk_usage(str(Path.home())).free / (1024 ** 3)
            block['disk_free_gb'] = round(free, 2)
        except OSError:
            pass
        block['uptime_s'] = round(time.time() - started, 1)
        tmp = output.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(block, ensure_ascii=False), encoding='utf-8')
            os.replace(str(tmp), str(output))
        except OSError:
            pass
        if args.duration and time.time() - started > args.duration:
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    sys.exit(main())
