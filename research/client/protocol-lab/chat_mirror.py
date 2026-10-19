#!/usr/bin/env python3
"""Chat-mirror hook: copy every outgoing in-game chat to the shadow observer.

Mechanism (static, 2026-10-19):
  * SANPK's ChatTo wrapper 0x42acea does: push msg; push id; call dword [0x4fb43c]
    (stdcall: callee cleans 8). So the real chat-send function address lives in
    the IAT slot 0x4fb43c, resolved per process.
  * We do NOT patch any code: we VirtualProtect the IAT page, store our stub in
    a fresh cave, point 0x4fb43c at the stub. The stub mirrors each send to the
    shadow member id (when the recipient looks like a member id 0x0A?????? and
    differs from the shadow, deduping by message pointer), then tail-jumps to
    the real function with the original arguments.

Usage (wine py32, inside the SENDER client's prefix):
  chat_mirror.py --ghost-id 178817775 --action install --state Z:\\...\\chat-mirror.json
  chat_mirror.py --action check   --state ...
  chat_mirror.py --action revert  --state ...

The shadow id changes every session; read it from the room member table
(remote_read_host.py prints '待秋至' -> id) before installing.
"""
import argparse
import ctypes as c
import json
import os
import struct
import sys
import time
from ctypes import wintypes as w

IAT_SLOT = 0x4FB43C
IAT_ORIG_BYTES = None  # no fixed bytes: read at install


def log(*a):
    print(*a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ghost-id', type=lambda s: int(s, 0), default=0)
    ap.add_argument('--action', choices=('install', 'check', 'revert'), default='check')
    ap.add_argument('--state', required=True)
    args = ap.parse_args()
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
    k.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
    k.VirtualAllocEx.restype = c.c_void_p
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

    def wr(addr, data, protect=True):
        old = w.DWORD(0)
        if protect:
            k.VirtualProtectEx(h, c.c_void_p(addr), len(data), 0x40, c.byref(old))
        buf = c.create_string_buffer(data, len(data))
        got = c.c_size_t()
        ok = k.WriteProcessMemory(h, c.c_void_p(addr), buf, len(data), c.byref(got)) and got.value == len(data)
        if protect:
            k.VirtualProtectEx(h, c.c_void_p(addr), len(data), old.value, c.byref(old))
        return ok

    state = {}
    try:
        state = json.loads(open(args.state).read())
    except (OSError, ValueError):
        state = {}
    same = state.get('pid') == pid and state.get('iat_orig') is not None
    if same:
        # confirm the slot still holds our stub
        cur = rd(IAT_SLOT, 4)
        ours = state.get('stub_addr')
        patched = cur is not None and ours and struct.unpack('<I', cur)[0] == int(ours, 16)
    else:
        patched = False

    if args.action == 'check':
        cur = rd(IAT_SLOT, 4)
        print(json.dumps({'pid': pid, 'iat_slot': hex(IAT_SLOT),
                          'slot_value': hex(struct.unpack('<I', cur)[0]) if cur else None,
                          'ours': patched, 'ghost_id': state.get('ghost_id')}))
        return 0

    if args.action == 'revert':
        if not patched:
            print(json.dumps({'action': 'revert', 'changed': False, 'reason': 'slot is not ours'}))
            return 0
        orig = int(state['iat_orig'], 16)
        ok = wr(IAT_SLOT, struct.pack('<I', orig))
        print(json.dumps({'action': 'revert', 'changed': bool(ok)}))
        return 0

    # install
    if patched:
        print(json.dumps({'action': 'install', 'already': True, 'stub': state.get('stub_addr')}))
        return 0
    if args.ghost_id <= 0:
        print(json.dumps({'error': 'install needs --ghost-id'}))
        return 1
    orig_fn = rd(IAT_SLOT, 4)
    if not orig_fn:
        print(json.dumps({'error': 'cannot read IAT slot'}))
        return 1
    orig_fn = struct.unpack('<I', orig_fn)[0]
    cave = k.VirtualAllocEx(h, None, 0x2000, 0x3000, 0x40)  # COMMIT|RESERVE, RWX
    if not cave:
        print(json.dumps({'error': 'VirtualAllocEx failed', 'err': k.GetLastError()}))
        return 1
    stub = cave
    blob = cave + 0x1000
    b = bytearray(0x40)
    struct.pack_into('<III', b, 0, orig_fn, args.ghost_id, 0)  # +0 orig, +4 ghost, +8 last_msg
    if not wr(blob, bytes(b), protect=False):
        print(json.dumps({'error': 'write blob failed'}))
        return 1
    # stub: guard id>>24==0x0a, != ghost, dedupe msg, mirror, then tail-jump original
    code = bytearray()
    A = lambda addr: struct.pack('<I', addr)
    code += bytes.fromhex('8b442404')            # mov eax,[esp+4]      (id)
    code += bytes.fromhex('c1e818')              # shr eax,24
    code += bytes.fromhex('83f80a')              # cmp eax,0x0a
    j1 = len(code); code += b'\x75\x00'          # jne real
    code += bytes.fromhex('8b442404')            # mov eax,[esp+4]
    code += b'\x3b\x05' + A(blob + 4)            # cmp eax,[blob+4]
    j2 = len(code); code += b'\x74\x00'          # je real
    code += bytes.fromhex('8b442408')            # mov eax,[esp+8]      (msg)
    code += b'\x3b\x05' + A(blob + 8)            # cmp eax,[blob+8]
    j3 = len(code); code += b'\x74\x00'          # je real
    code += b'\x89\x05' + A(blob + 8)            # mov [blob+8],eax
    code += bytes.fromhex('8b442408')            # mov eax,[esp+8]
    code += b'\x50'                              # push eax  (msg)
    code += b'\xff\x35' + A(blob + 4)            # push dword [blob+4] (ghost)
    code += b'\xff\x15' + A(blob + 0)            # call dword [blob+0]
    real = len(code)
    # The original arguments are already in place ([esp+4]=id, [esp+8]=msg):
    # tail-jump straight to the original function (stdcall cleans its 8 bytes).
    code += b'\xff\x25' + A(blob + 0)            # jmp dword [blob+0]
    # patch short jumps
    code[j1 + 1] = real - (j1 + 2)
    code[j2 + 1] = real - (j2 + 2)
    code[j3 + 1] = real - (j3 + 2)
    if not wr(stub, bytes(code), protect=False):
        print(json.dumps({'error': 'write stub failed'}))
        return 1
    if rd(stub, len(code)) != bytes(code):
        print(json.dumps({'error': 'stub readback mismatch'}))
        return 1
    if not wr(IAT_SLOT, struct.pack('<I', stub)):
        print(json.dumps({'error': 'IAT patch failed'}))
        return 1
    state = {'schema': 'chat-mirror-1', 'pid': pid, 'created_wall': time.time(),
             'iat_slot': hex(IAT_SLOT), 'iat_orig': hex(orig_fn),
             'stub_addr': hex(stub), 'blob_addr': hex(blob), 'ghost_id': args.ghost_id,
             'code_sha': __import__('hashlib').sha256(bytes(code)).hexdigest()}
    open(args.state, 'w').write(json.dumps(state, indent=1))
    print(json.dumps({'action': 'install', 'ok': True, 'pid': pid,
                      'iat_orig': hex(orig_fn), 'stub': hex(stub), 'ghost_id': args.ghost_id}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
