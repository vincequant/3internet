#!/usr/bin/env python3
"""P60 injector — generic faction command (runs under Win32 py32 in the prefix).

Arms ONE generic agent (p60_generic_cmd_build.py) that builds a command object
with the game's own constructor and hands it to the game's own 0x42A7D4 send.
Presets cover the commands verified on 2026-10-19:

  train      kind 18 subtype 0   (步/騎/弓 training; actor + troop + value + extra)
  alms       kind 18 subtype 2   (施捨)
  rice       kind 18 subtype 3   (米交易: buy=0 sell / 1 buy)
  build      kind 18 subtype 4   (建設: build-type 4..9 at packed XY)
  personnel  kind 20 subtype 0/1/2/5 (actor + target general id)
  phaseend   kind 21             (end my command phase)

Single shot: refuses if the receipt exists; the agent itself is once-only.

Usage:
  python.exe p60_generic_cmd_inject.py --preset train --actor 1 --troop 0 \
      --value 100 --extra 0 --agent-bin 'Z:\\...\\agent_generic.bin' \
      --koeinm 'C:\\sgi\\run-3.5\\3I\\Koeinm.dll' \
      --flag 'Z:\\...\\p60_go.flag' --receipt 'Z:\\...\\p60_receipt.bin' \
      [--state 'Z:\\...\\p60_state.json'] [--plan] [--check] [--force]
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p51_shadow_inject as base  # noqa: E402
import p60_generic_cmd_build as build  # noqa: E402

PRESET_CLASS = {'train': 'domestic', 'alms': 'domestic', 'rice': 'domestic', 'build': 'domestic',
                'personnel': 'personnel', 'phaseend': 'phaseend'}


def make_fields(args):
    preset = args.preset
    if preset == 'train':
        return build.fields_train(args.actor, args.troop, args.value, args.extra), 'domestic'
    if preset == 'alms':
        return build.fields_alms(args.actor, args.value, args.extra), 'domestic'
    if preset == 'rice':
        return build.fields_rice(args.actor, args.buy, args.value, args.extra), 'domestic'
    if preset == 'build':
        return (build.fields_build(args.actor, args.build_type, args.x, args.y,
                                   args.value, args.extra), 'domestic')
    if preset == 'personnel':
        return build.fields_personnel(args.actor, args.subtype, args.target), 'personnel'
    if preset == 'phaseend':
        return build.fields_phaseend(), 'phaseend'
    raise SystemExit('unknown preset ' + preset)


def expected_wire(cls, fields):
    """Rebuild the exact payload the game will serialize (for the plan print)."""
    ctor_va, size, kind, _vt = build.CLASSES[cls]
    name = {'domestic': 'CSanInetDomesticCmd', 'personnel': 'CSanInetPersonnelCmd',
            'phaseend': 'CSanInetPhaseEndCmd', 'diplomacy': 'CSanInetDiplomacyCmd'}[cls]
    base = {0x04: kind, 0x08: 0, 0x0C: 0}
    for off, val in fields:
        base[off] = val
    body = struct.pack('<3i', base[0x04], base[0x08], base[0x0C]) + b'\x00'
    if cls == 'domestic':
        body += struct.pack('<4i', base[0x14], base[0x18], base[0x1C], base[0x20])
    elif cls == 'personnel':
        body += struct.pack('<2i', base[0x14], base[0x18])
    return (struct.pack('<3H', 0xFFFF, 1, len(name)) + name.encode('ascii') + body)


def preflight_class(read_proc, sanpk_base, cls):
    ctor_va, size, kind, vtable_va = build.CLASSES[cls]
    ctor = read_proc(sanpk_base + (ctor_va - build.BASE_PREFERRED), 40)
    if ctor is None:
        raise SystemExit('cannot read ctor for ' + cls)
    if bytes([0x6A, kind & 0xFF]) not in ctor:
        raise SystemExit('%s ctor does not push kind %d (wrong build?)' % (cls, kind))
    vt = struct.unpack('<I', read_proc(sanpk_base + (vtable_va - build.BASE_PREFERRED), 4))[0]
    if vt - sanpk_base not in (build.RVA_GETRUNTIMECLASS, 0x436B13 - 0x400000,
                               0x436CB8 - 0x400000, 0x436DBF - 0x400000):
        raise SystemExit('%s getter mismatch 0x%x' % (cls, vt))
    return {'ctor_prologue': ctor[:8].hex(), 'getter_rva': vt - sanpk_base}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-name', default='SANPK.exe')
    ap.add_argument('--koeinm', default=r'C:\sgi\run-3.5\3I\Koeinm.dll')
    ap.add_argument('--agent-bin', required=True)
    ap.add_argument('--preset', required=True, choices=sorted(PRESET_CLASS))
    ap.add_argument('--actor', type=int, default=0)
    ap.add_argument('--troop', type=int, default=0)
    ap.add_argument('--buy', type=int, default=0)
    ap.add_argument('--build-type', type=int, default=7)
    ap.add_argument('--x', type=int, default=0)
    ap.add_argument('--y', type=int, default=0)
    ap.add_argument('--value', type=int, default=0)
    ap.add_argument('--extra', type=int, default=0)
    ap.add_argument('--subtype', type=int, default=0)
    ap.add_argument('--target', type=int, default=-1)
    ap.add_argument('--flag', required=True)
    ap.add_argument('--receipt', required=True)
    ap.add_argument('--require-phase', type=int, default=0,
                    help='0 = fire in any phase; 1 = only in the command phase (stage gate)')
    ap.add_argument('--state')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    fields, cls = make_fields(args)
    c, w, k = base._win()
    targets = base.find_process(args.target_name)
    if len(targets) != 1:
        raise SystemExit('%d processes named %s (need exactly 1)'
                         % (len(targets), args.target_name))
    pid = targets[0][0]
    h = k.OpenProcess(0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed err=%d' % c.get_last_error())
    created = base.process_creation(pid)

    def read_proc(addr, size):
        buf = c.create_string_buffer(size)
        got = c.c_size_t()
        ok = k.ReadProcessMemory(h, c.c_void_p(addr), buf, size, c.byref(got))
        return buf.raw if ok and got.value == size else None

    def write_proc(addr, data):
        got = c.c_size_t()
        ok = k.WriteProcessMemory(h, c.c_void_p(addr), data, len(data), c.byref(got))
        return bool(ok) and got.value == len(data)

    try:
        sanpk = base.find_module(pid, 'SANPK.exe')
        koeinm = base.find_module(pid, 'Koeinm.dll')
        if not sanpk or not koeinm:
            raise SystemExit('target modules missing')
        exports = base.parse_exports(args.koeinm)
        sanpk_base, koeinm_base = int(sanpk['base']), int(koeinm['base'])
        anchors = preflight_class(read_proc, sanpk_base, cls)
        # shared send path anchor
        send_prologue = read_proc(sanpk_base + build.RVA_SEND, 4)
        pointers = base.kernel32_pointers()
        k32_self = pointers.pop('_kernel32_base')
        target_k32 = base.find_module(pid, 'kernel32.dll')
        if not target_k32 or target_k32['base'] != k32_self:
            raise SystemExit('kernel32 base mismatch')
        pointers['is_connected'] = koeinm_base + exports['_NetMsg_IsConnected@0']
        pointers['get_ip'] = koeinm_base + exports['_NetMsg_GetIPAddress@4']
        pointers['core_global'] = sanpk_base + build.RVA_CORE_GLOBAL
        blob = build.build_blob(pointers, cls=cls, fields=fields, sanpk_base=sanpk_base,
                               flag_path=args.flag, receipt_path=args.receipt,
                               phase_req=args.require_phase)
        wire = expected_wire(cls, fields)
        plan = {'mode': 'generic_cmd', 'preset': args.preset, 'class': cls, 'pid': pid,
                'sanpk': hex(sanpk_base), 'koeinm': hex(koeinm_base),
                'class_check': {kk: (hex(v) if isinstance(v, int) else v)
                                for kk, v in anchors.items()},
                'send_prologue': send_prologue.hex() if send_prologue else None,
                'fields': [{'off': hex(o), 'val': v} for o, v in fields],
                'require_phase': args.require_phase,
                'expected_wire_len': len(wire), 'expected_wire_hex': wire.hex(),
                'flag': args.flag, 'receipt': args.receipt}
        if args.check:
            rp = Path(args.receipt)
            st = Path(args.state) if args.state else None
            plan['receipt_exists'] = rp.exists()
            plan['receipt'] = (build.parse_receipt(rp.read_bytes())
                               if rp.exists() and rp.stat().st_size == build.RECEIPT_SIZE else None)
            plan['state'] = (json.loads(st.read_text(encoding='utf-8')) if st and st.exists() else None)
            print(json.dumps({'status': 'ok', **plan}, ensure_ascii=False))
            return
        if args.plan:
            plan['plan_only'] = True
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return
        rp = Path(args.receipt)
        if rp.exists() and not args.force:
            raise SystemExit('receipt exists (%s); one-shot discipline' % args.receipt)
        code = Path(args.agent_bin).read_bytes()
        size = len(code) + len(blob) + 0x40
        addr = k.VirtualAllocEx(h, None, size, 0x3000, 0x40)
        if not addr:
            raise SystemExit('VirtualAllocEx failed err=%d' % c.get_last_error())
        blob_addr = addr + ((len(code) + 0xF) & ~0xF)
        if not write_proc(addr, code) or not write_proc(blob_addr, blob):
            raise SystemExit('WriteProcessMemory failed err=%d' % c.get_last_error())
        if read_proc(addr, len(code)) != code or read_proc(blob_addr, len(blob)) != blob:
            raise SystemExit('readback mismatch')
        tid = w.DWORD(0)
        th = k.CreateRemoteThread(h, None, 0, c.c_void_p(addr), c.c_void_p(blob_addr),
                                  0, c.byref(tid))
        if not th:
            raise SystemExit('CreateRemoteThread failed err=%d' % c.get_last_error())
        k.CloseHandle(th)
        out = dict(plan, code_addr=hex(addr), blob_addr=hex(blob_addr),
                   thread_id=tid.value, creation=created)
        if args.state:
            Path(args.state).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    main()
