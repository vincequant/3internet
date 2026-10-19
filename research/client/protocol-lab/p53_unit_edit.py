#!/usr/bin/env python3
"""Read/write a shadow-client unit's editable fields (research tool).

Fields and native clamps come from the P53 unit model (static consumers/setters):
  soldiers    兵力   unit+0x15  u32  0..100000   (0x477444..0x47746c clamps)
  rice        兵粮   unit+0x19  u32  0..100000   (0x4779e9..0x477a49 clamps)
  morale      士气   unit+0x1d  u8   0..100      (transport 0..50; 0x47750e setter)
  training    训练   unit+0x29  u8   0..100      (0x47a9f8/0x47b1f4 inputs)
  move_left   剩余移动 unit+0x20 u8   0..255      (0x430366)

Rules: verify the vtable is a known unit type before any write; clamp to the
native range; write with VirtualProtectEx; read back and record before/after;
one edit per call; --revert restores the recorded before-value.

Usage (wine py32, inside prefix-fengye-shadow):
  p53_unit_edit.py --address 0x1234abcd --read
  p53_unit_edit.py --address 0x1234abcd --field soldiers --value 5000 --state Z:\\...\\unit-edit.json
  p53_unit_edit.py --revert --state Z:\\...\\unit-edit.json
"""
import argparse
import ctypes as c
import json
import os
import struct
import sys
import time

from ctypes import wintypes as w

UNIT_TYPES = {
    0x508678: '战略部队', 0x508878: '步兵', 0x508a60: '强化步兵',
    0x508c48: '重装步兵', 0x508e30: '骑兵', 0x509018: '强化骑兵',
    0x509200: '铁骑兵', 0x5093e8: '弓兵', 0x5095d0: '强弓兵',
    0x5097b8: '重装弓兵', 0x5099d0: '运输兵', 0x50bdb8: '游荡部队',
}
FIELDS = {
    'soldiers': ('兵力', 0x15, '<I', 100000),
    'rice': ('兵粮', 0x19, '<I', 100000),
    'morale': ('士气', 0x1d, '<B', 100),
    'training': ('训练', 0x29, '<B', 100),
    'move_left': ('剩余移动', 0x20, '<B', 255),
}
TRANSPORT_VT = 0x5099d0

# 武将对象（vtable 0x5056f0；容器 core+0x514）：第三行"统武"= 统率+武力。
GENERAL_VT = 0x5056f0
GENERAL_FIELDS = {
    'lead':  ('统率', 0x25, '<B', 255),
    'war':   ('武力', 0x26, '<B', 255),
    'intel': ('智力', 0x27, '<B', 255),
    'pol':   ('政治', 0x28, '<B', 255),
    'cha':   ('魅力', 0x29, '<B', 255),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--address', type=lambda s: int(s, 16), default=None)
    ap.add_argument('--field', choices=sorted(FIELDS) + sorted(GENERAL_FIELDS), default=None)
    ap.add_argument('--general-id', type=int, default=None)
    ap.add_argument('--value', type=int, default=None)
    ap.add_argument('--read', action='store_true')
    ap.add_argument('--revert', action='store_true')
    ap.add_argument('--state', default='')
    ap.add_argument('--bridge', default=r'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\bridge')
    args = ap.parse_args()
    args_bridge = args.bridge if hasattr(args, 'bridge') else None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe in this prefix'}))
        return 1
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
    h = k.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess failed', 'err': k.GetLastError()}))
        return 1

    def rd(addr, n):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    def wr(addr, data):
        old = w.DWORD(0)
        k.VirtualProtectEx(h, c.c_void_p(addr), len(data), 0x40, c.byref(old))
        buf = c.create_string_buffer(data, len(data))
        got = c.c_size_t()
        ok = (k.WriteProcessMemory(h, c.c_void_p(addr), buf, len(data), c.byref(got))
              and got.value == len(data))
        k.VirtualProtectEx(h, c.c_void_p(addr), len(data), old.value, c.byref(old))
        return ok

    state = {'schema': 'p53-unit-edit-1', 'edits': []}
    if args.state:
        try:
            state = json.loads(open(args.state).read())
        except (OSError, ValueError):
            pass

    if args.revert:
        if not state.get('edits'):
            print(json.dumps({'action': 'revert', 'changed': False, 'reason': 'no recorded edits'}))
            return 0
        edit = state['edits'][-1]
        addr = int(edit['address'], 16)
        field = edit['field']
        if field.startswith('general:'):
            _, off, fmt, _ = GENERAL_FIELDS[field.split(':', 1)[1]]
        else:
            _, off, fmt, _ = FIELDS[field]
        data = struct.pack(fmt, int(edit['before']))
        ok = wr(addr + off, data)
        back = rd(addr + off, len(data))
        state['edits'].pop()
        if args.state:
            open(args.state, 'w').write(json.dumps(state, indent=1))
        print(json.dumps({'action': 'revert', 'changed': bool(ok), 'field': field,
                          'now': struct.unpack(fmt, back)[0] if back else None}))
        return 0

    def walk_generals(core, limit=2048):
        address = core + 0x514
        header = rd(address, 28)
        if header is None:
            raise ValueError('general container unreadable')
        head, tail, count = struct.unpack_from('<III', header, 4)
        if count > limit:
            raise ValueError('container bound')
        node, prev, seen, objs = head, 0, set(), []
        for _ in range(count):
            if node < 0x10000 or node in seen:
                raise ValueError('cyclic/short list')
            seen.add(node)
            raw = rd(node, 12)
            if raw is None:
                raise ValueError('node unreadable')
            nxt, back, obj = struct.unpack('<III', raw)
            if back != prev or obj < 0x10000 or obj in objs:
                raise ValueError('identity mismatch')
            objs.append(obj)
            prev, node = node, nxt
        if node or prev != tail:
            raise ValueError('count/tail mismatch')
        return objs

    if args.general_id is not None:
        os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
        sys.path.insert(0, args_bridge)
        from collector import Collector
        col = Collector(pid)
        try:
            col.bind()
            core = int(col.core)
        finally:
            col.close()
        found = None
        for obj in walk_generals(core):
            head = rd(obj, 12)
            if head is None or struct.unpack_from('<I', head)[0] != GENERAL_VT:
                continue
            if struct.unpack_from('<H', head, 10)[0] == args.general_id:
                found = obj
                break
        if found is None:
            print(json.dumps({'error': 'general not found', 'id': args.general_id}))
            return 1
        vals = {}
        for key, (label, off, fmt, cap) in GENERAL_FIELDS.items():
            raw = rd(found + off, struct.calcsize(fmt))
            vals[key] = {'label': label, 'value': struct.unpack(fmt, raw)[0] if raw else None, 'max': cap}
        if args.read or args.field is None:
            print(json.dumps({'general_id': args.general_id, 'address': hex(found),
                              'attributes': vals,
                              'blade_total': (vals['lead']['value'] + vals['war']['value'])
                              if vals['lead']['value'] is not None and vals['war']['value'] is not None else None},
                             ensure_ascii=False))
            return 0
        if args.value is None:
            print(json.dumps({'error': 'need --value'}))
            return 1
        label, off, fmt, cap = GENERAL_FIELDS[args.field]
        size = struct.calcsize(fmt)
        raw = rd(found + off, size)
        if raw is None:
            print(json.dumps({'error': 'field unreadable'}))
            return 1
        before = struct.unpack(fmt, raw)[0]
        value = max(0, min(int(args.value), cap))
        ok = wr(found + off, struct.pack(fmt, value))
        back = rd(found + off, size)
        after = struct.unpack(fmt, back)[0] if back else None
        state.setdefault('edits', []).append({'wall': time.time(), 'address': hex(found),
                                              'field': 'general:' + args.field,
                                              'before': before, 'requested': int(args.value),
                                              'written': value, 'after': after})
        if args.state:
            open(args.state, 'w').write(json.dumps(state, indent=1))
        print(json.dumps({'action': 'write_general', 'ok': bool(ok and after == value),
                          'general_id': args.general_id, 'field': args.field, 'label': label,
                          'before': before, 'requested': int(args.value), 'after': after},
                         ensure_ascii=False))
        return 0 if (ok and after == value) else 2

    if not args.address:
        print(json.dumps({'error': 'need --address'}))
        return 1
    vt_raw = rd(args.address, 4)
    if not vt_raw:
        print(json.dumps({'error': 'unit address unreadable'}))
        return 1
    vt = struct.unpack('<I', vt_raw)[0]
    if vt not in UNIT_TYPES:
        print(json.dumps({'error': 'vtable is not a known unit type', 'vtable': hex(vt)}))
        return 1
    kind = UNIT_TYPES[vt]
    if args.read or args.field is None:
        vals = {}
        for key, (label, off, fmt, cap) in FIELDS.items():
            raw = rd(args.address + off, struct.calcsize(fmt))
            vals[key] = {'label': label, 'value': struct.unpack(fmt, raw)[0] if raw else None,
                         'max': min(cap, 50) if (key == 'morale' and vt == TRANSPORT_VT) else cap}
        print(json.dumps({'address': hex(args.address), 'kind': kind, 'fields': vals},
                         ensure_ascii=False))
        return 0
    if args.value is None:
        print(json.dumps({'error': 'need --value'}))
        return 1
    label, off, fmt, cap = FIELDS[args.field]
    if args.field == 'morale' and vt == TRANSPORT_VT:
        cap = min(cap, 50)
    size = struct.calcsize(fmt)
    raw = rd(args.address + off, size)
    if raw is None:
        print(json.dumps({'error': 'field unreadable'}))
        return 1
    before = struct.unpack(fmt, raw)[0]
    value = max(0, min(int(args.value), cap))
    ok = wr(args.address + off, struct.pack(fmt, value))
    back = rd(args.address + off, size)
    after = struct.unpack(fmt, back)[0] if back else None
    edit = {'wall': time.time(), 'address': hex(args.address), 'field': args.field,
            'before': before, 'requested': int(args.value), 'written': value, 'after': after}
    state.setdefault('edits', []).append(edit)
    if args.state:
        open(args.state, 'w').write(json.dumps(state, indent=1))
    print(json.dumps({'action': 'write', 'ok': bool(ok and after == value), 'kind': kind,
                      'field': args.field, 'before': before, 'requested': int(args.value),
                      'written': value, 'after': after}, ensure_ascii=False))
    return 0 if (ok and after == value) else 2


if __name__ == '__main__':
    sys.exit(main())
