#!/usr/bin/env python3
"""P59 injector — runs under Win32 py32 inside the shadow Wine prefix.

Injects ONE interface-free CSanInetDomesticCmd agent (p59_domestic_cmd_build.py)
into a running SANPK.exe. The agent polls a trigger file; on the operator's
signal it builds exactly one kind-18 training command with the game's own
constructor (0x4369f6) and hands it to the game's own send path (0x42a7d4),
then writes a binary receipt and stays inert.

Discipline:
  * single shot — refuses when a receipt exists or the same process is already
    armed (use --reset to move the stale receipt/state away first, --force to
    override the arm-once check);
  * pre-flight — verifies the target module really is SANPK 3.5 (vtable[2],
    CRuntimeClass size/schema/name) before writing anything;
  * no game-file, no save, no UI, no seat change; only our blob + a remote
    thread in the shadow client.

Usage (under wine py32):
  python.exe p59_domestic_inject.py \
      --target-name SANPK.exe --koeinm 'C:\\sgi\\run-3.5\\3I\\Koeinm.dll' \
      --actor 12 --parameter 1 --value 95 --extra 0 \
      --agent-bin 'Z:\\...\\agent_domestic.bin' \
      --flag 'Z:\\...\\p59_go.flag' --receipt 'Z:\\...\\p59_receipt.bin' \
      --state 'Z:\\...\\p59_state.json' [--plan] [--check]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p51_shadow_inject as base  # noqa: E402  (win32 layer + PE export parser)
import p59_domestic_cmd_build as build  # noqa: E402

SANPK_SHA_LIVE = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'


def preflight(read_proc, sanpk_base, koeinm_base, exports):
    """Reject anything that is not the analysed SANPK 3.5 / Koeinm build."""
    checks = {}

    def u32(addr):
        raw = read_proc(addr, 4)
        if raw is None:
            raise SystemExit('read failed at 0x%x' % addr)
        return struct.unpack('<I', raw)[0]

    checks['vtable_serialize'] = u32(sanpk_base + build.RVA_VTABLE + 8) - sanpk_base
    if checks['vtable_serialize'] != build.RVA_SERIALIZE:
        raise SystemExit('unexpected vtable[2] 0x%x (not SANPK 3.5 Serialize)'
                         % checks['vtable_serialize'])
    checks['vtable_getruntimeclass'] = u32(sanpk_base + build.RVA_VTABLE) - sanpk_base
    if checks['vtable_getruntimeclass'] != build.RVA_GETRUNTIMECLASS:
        raise SystemExit('unexpected vtable[0] 0x%x' % checks['vtable_getruntimeclass'])
    checks['class_name_ptr'] = u32(sanpk_base + build.RVA_CLASS) - sanpk_base
    if checks['class_name_ptr'] != build.RVA_NAME:
        raise SystemExit('unexpected CRuntimeClass::name 0x%x' % checks['class_name_ptr'])
    checks['class_size'] = u32(sanpk_base + build.RVA_CLASS + 4)
    checks['class_schema'] = u32(sanpk_base + build.RVA_CLASS + 8)
    if checks['class_size'] != build.A_SIZE or checks['class_schema'] != build.A_SCHEMA:
        raise SystemExit('unexpected CRuntimeClass size/schema %r/%r'
                         % (checks['class_size'], checks['class_schema']))
    checks['class_factory'] = u32(sanpk_base + build.RVA_CLASS + 0x0C) - sanpk_base
    if checks['class_factory'] != build.RVA_FACTORY:
        raise SystemExit('unexpected factory 0x%x' % checks['class_factory'])
    ctor = read_proc(sanpk_base + build.RVA_CTOR, 8)
    if ctor is None or ctor[:5] != b'\x56\x57\x33\xff\x68':
        raise SystemExit('ctor prologue mismatch: %r' % (ctor,))
    checks['send_prologue'] = read_proc(sanpk_base + build.RVA_SEND, 4).hex()
    checks['core_global'] = sanpk_base + build.RVA_CORE_GLOBAL
    checks['send_this'] = sanpk_base + build.RVA_SEND_THIS
    for name in ('_NetMsg_IsConnected@0', '_NetMsg_GetIPAddress@4'):
        if name not in exports:
            raise SystemExit('Koeinm is missing export ' + name)
    checks['is_connected'] = koeinm_base + exports['_NetMsg_IsConnected@0']
    checks['get_ip'] = koeinm_base + exports['_NetMsg_GetIPAddress@4']
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-name', default='SANPK.exe')
    ap.add_argument('--koeinm', default=r'C:\sgi\run-3.5\3I\Koeinm.dll',
                    help='Koeinm.dll path used only to read export RVAs locally')
    ap.add_argument('--agent-bin', required=True)
    ap.add_argument('--actor', type=int, required=True, help='target force id 0..31')
    ap.add_argument('--parameter', type=int, default=1, help='0=infantry 1=cavalry 2=archer')
    ap.add_argument('--value', type=int, default=95, help='kind-18 value operand (see notes)')
    ap.add_argument('--extra', type=int, default=0)
    ap.add_argument('--flag', required=True, help='trigger file (agent fires when it exists)')
    ap.add_argument('--receipt', required=True)
    ap.add_argument('--state', help='state json path')
    ap.add_argument('--plan', action='store_true', help='print the plan, write nothing')
    ap.add_argument('--check', action='store_true', help='read back state, write nothing')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    c, w, k = base._win()
    targets = base.find_process(args.target_name)
    if not targets:
        raise SystemExit('no process named ' + args.target_name)
    if len(targets) != 1:
        raise SystemExit('%d processes named %s (need exactly 1)'
                         % (len(targets), args.target_name))
    pid = targets[0][0]
    RIGHTS = 0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400
    h = k.OpenProcess(RIGHTS, False, pid)
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
        if not sanpk:
            raise SystemExit('SANPK.exe module not found in target')
        if not koeinm:
            raise SystemExit('Koeinm.dll module not found in target')
        exports = base.parse_exports(args.koeinm)
        sanpk_base, koeinm_base = int(sanpk['base']), int(koeinm['base'])
        anchors = preflight(read_proc, sanpk_base, koeinm_base, exports)

        code = Path(args.agent_bin).read_bytes()
        pointers = base.kernel32_pointers()
        k32_self = pointers.pop('_kernel32_base')
        target_k32 = base.find_module(pid, 'kernel32.dll')
        if not target_k32:
            raise SystemExit('cannot enumerate target kernel32')
        if target_k32['base'] != k32_self:
            raise SystemExit('kernel32 base differs (self=0x%x target=0x%x)'
                             % (k32_self, target_k32['base']))
        pointers['is_connected'] = anchors['is_connected']
        pointers['get_ip'] = anchors['get_ip']
        pointers['core_global'] = anchors['core_global']
        blob = build.build_blob(pointers, actor=args.actor, parameter=args.parameter,
                                value=args.value, extra=args.extra, sanpk_base=sanpk_base,
                                flag_path=args.flag, receipt_path=args.receipt,
                                send_this_addr=anchors['send_this'])
        plan = {'mode': 'domestic_cmd', 'pid': pid, 'target': args.target_name,
                'sanpk': {'base': hex(sanpk_base), 'via': sanpk.get('via')},
                'koeinm': {'base': hex(koeinm_base), 'via': koeinm.get('via')},
                'anchors': {key: (hex(v) if isinstance(v, int) else v) for key, v in anchors.items()},
                'command': {'class': build.CLASS_NAME, 'kind': 18, 'subtype': 0,
                            'actor': args.actor, 'parameter': args.parameter,
                            'value': args.value, 'extra': args.extra},
                'expected_wire_hex': build.expected_wire(args.actor, args.parameter,
                                                         args.value, args.extra).hex(),
                'code_size': len(code),
                'code_sha256': __import__('hashlib').sha256(code).hexdigest(),
                'blob_size': len(blob), 'flag': args.flag, 'receipt': args.receipt}

        if args.check:
            receipt = Path(args.receipt)
            state = Path(args.state) if args.state else None
            plan['receipt_exists'] = receipt.exists()
            plan['receipt'] = (build.parse_receipt(receipt.read_bytes())
                               if receipt.exists() and receipt.stat().st_size == build.RECEIPT_SIZE
                               else None)
            plan['state'] = (json.loads(state.read_text(encoding='utf-8'))
                             if state and state.exists() else None)
            print(json.dumps({'status': 'ok', **plan}, ensure_ascii=False))
            return
        if args.plan:
            plan['plan_only'] = True
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return

        receipt = Path(args.receipt)
        if receipt.exists() and not args.force:
            raise SystemExit('receipt already exists (%s) — one-shot discipline; '
                             'move it away first' % args.receipt)
        if args.state and Path(args.state).exists() and not args.force:
            prior = json.loads(Path(args.state).read_text(encoding='utf-8'))
            if prior.get('pid') == pid and prior.get('creation') == created:
                probe = read_proc(int(prior['blob_addr'], 16), 4) if prior.get('blob_addr') else None
                if probe and struct.unpack('<I', probe)[0] == build.MAGIC:
                    raise SystemExit('already armed in pid %d (blob %s); --force to override'
                                     % (pid, prior['blob_addr']))

        size = len(code) + len(blob) + 0x40
        addr = k.VirtualAllocEx(h, None, size, 0x3000, 0x40)
        if not addr:
            raise SystemExit('VirtualAllocEx failed err=%d' % c.get_last_error())
        blob_addr = addr + ((len(code) + 0xF) & ~0xF)
        if not write_proc(addr, code) or not write_proc(blob_addr, blob):
            raise SystemExit('WriteProcessMemory failed err=%d' % c.get_last_error())
        if read_proc(addr, len(code)) != code:
            raise SystemExit('code verification readback mismatch')
        if read_proc(blob_addr, len(blob)) != blob:
            raise SystemExit('blob verification readback mismatch')
        tid = w.DWORD(0)
        th = k.CreateRemoteThread(h, None, 0, c.c_void_p(addr), c.c_void_p(blob_addr),
                                  0, c.byref(tid))
        if not th:
            raise SystemExit('CreateRemoteThread failed err=%d' % c.get_last_error())
        k.CloseHandle(th)
        result = dict(plan, code_addr=hex(addr), blob_addr=hex(blob_addr),
                      thread_id=tid.value, creation=created)
        if args.state:
            Path(args.state).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    main()
