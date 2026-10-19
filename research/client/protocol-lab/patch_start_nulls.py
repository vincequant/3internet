#!/usr/bin/env python3
"""Runtime guards so a missing city does not freeze or kill the opening.

The start tick calls 0x44FFF4 (find city by id) and then reads the result
with no null check. A partial city list makes that read fault, the tick
lock at 0x53BA54 stays 1, and the clock never leaves 0:00. Passing the
first site lets the round worker fault the same way at 0x433ED4.
The 2026-10-19 16:59 exit was the same lookup at 0x469244: a status-1
general's city was missing, then 0x4d3202 read the null pointer.

Opening and training guards, one freshly allocated cave, memory only:

  0x445E98  my-force list A     null -> 0x445E3F, else original compare
  0x445FE3  my-force list B     null -> 0x445F79, else original compare
  0x45C4E1  round city read     null -> 0x45C518, else original call
  0x44D694  round city owner    null -> 0x44D768, else original owner read
  0x49B819  lord byte           null -> 0x49B822, else original compare
  0x46924B  wild-general city   null -> 0x469278, else push and continue

Training sites also skip missing results, zero divisors and invalid virtual
calls. The 18:24:26 crash returned to 0x48437F from call [eax+0x84]; that
call already has one stack argument, which the skip path must remove.
The 18:41:42 crash reached 0x4183C0 with this=0xfffff95a; skip that
function through its existing epilogue for null or negative object pointers.
The 18:47:33 crash used the same invalid this at 0x49B0E3; that predicate
returns 0 through its original false-return path for null or negative this.
The 18:51:23 crash reached 0x4B0822 with this=0xfffffa5a; its skip path
must restore the saved SEH chain and pop the one argument via the epilogue.
The first train-list hook covered loop target 0x4B0825 and caused the
18:56 start regression. Hook the five-byte pre-loop setup at 0x4B081D
instead; the original mov/test and every loop-back entry must stay intact.

Usage (wine py32, inside the target prefix):
  patch_start_nulls.py <pid>
  patch_start_nulls.py <pid> --clear-lock
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import struct
import sys
from ctypes import wintypes as w

LOCK_VA = 0x53BA54
# The game's own recorder only keeps access violations. Widen it so a divide-by-zero
# or illegal instruction is written too. cmp/jne at this address, log path falls through.
RECORDER_AT = 0x56140F
RECORDER_OLD = bytes.fromhex('8138050000c00f85b9000000')
RECORDER_LOG = 0x56141B
RECORDER_DONE = 0x5614D4
RECORDER_CODES = (
    0xC0000005,  # access violation
    0xC0000094,  # integer divide by zero
    0xC0000095,  # integer overflow
    0xC000001D,  # illegal instruction
    0xC00000FD,  # stack overflow
    0xC0000096,  # privileged instruction
)
PAGE = 0x40
MEM = 0x3000
ACCESS = 0x0010 | 0x0020 | 0x0008
TRAIN_LIST_BODY_AT = 0x4B0822
TRAIN_LIST_BODY_ORIG = bytes.fromhex('8b770485f6')


def rel32(src_next: int, dst: int) -> bytes:
    return struct.pack('<i', dst - src_next)


def hook_bytes(site: int, cave: int, n: int) -> bytes:
    if n < 5:
        raise ValueError(n)
    return b'\xe9' + rel32(site + 5, cave) + b'\x90' * (n - 5)


def is_hook(got: bytes, n: int) -> bool:
    return got[:1] == b'\xe9' and (n == 5 or got[5:6] == b'\x90')


def recorder_stub(cave: int) -> bytes:
    """Log access violations and the exceptions that exit without one. Other codes skip the log."""
    at = cave + 0x220
    n = len(RECORDER_CODES)
    blob = bytearray()
    for code in RECORDER_CODES:
        blob += b'\x81\x38' + struct.pack('<I', code) + b'\x0f\x84' + b'\x00\x00\x00\x00'
    blob += b'\xe9' + b'\x00\x00\x00\x00'
    blob += b'\xe9' + b'\x00\x00\x00\x00'
    log_at = at + n * 12 + 5
    for i in range(n):
        je_next = at + i * 12 + 12
        struct.pack_into('<i', blob, i * 12 + 8, log_at - je_next)
    done_next = at + n * 12 + 5
    struct.pack_into('<i', blob, n * 12 + 1, RECORDER_DONE - done_next)
    log_next = log_at + 5
    struct.pack_into('<i', blob, n * 12 + 6, RECORDER_LOG - log_next)
    return bytes(blob)


SITES = (
    # name, va, original bytes, cave offset
    ('myforce-a', 0x445E98, bytes.fromhex('0fbf48083b4d'), 0x00),
    ('myforce-b', 0x445FE3, bytes.fromhex('0fbf48083b4d'), 0x20),
    ('round-city', 0x45C4E1, bytes.fromhex('8d4de0518bc8'), 0x40),
    ('round-owner', 0x44D694, bytes.fromhex('8945ec8bcb0f'), 0x60),
    ('lord-byte', 0x49B819, bytes.fromhex('80b883000000'), 0x80),
    # 5-byte push. The mov ecx,eax just before it has already run.
    ('wild-city', 0x46924B, bytes.fromhex('6870335300'), 0xA0),
    # Repeated cavalry training: vfunc result is null, then 0x4858df writes 13 through it.
    ('train-result', 0x4858DF, bytes.fromhex('c7000d000000'), 0xC0),
    # Overlapped training: lookup returns null, then a word or byte is read from it.
    ('train-word', 0x4AE36F, bytes.fromhex('0fb700eb10'), 0xE0),
    ('train-byte', 0x4AE374, bytes.fromhex('ff7424088b'), 0x100),
    # Training recalc divides by a count. Zero exits the process with no access-violation record.
    ('train-div-a', 0x42DBA2, bytes.fromhex('8b4e3a0faf4e4299f7f9'), 0x140),
    ('train-div-b', 0x42DBB6, bytes.fromhex('99f77e468bce'), 0x160),
    # Training step divides by the per-click amount. Zero exits with no access-violation record.
    ('train-div-c', 0x484321, bytes.fromhex('8bc88b45082b450c99f7f9'), 0x180),
    # After a zero training step the game calls through a bad pointer (seen EIP 0x66e8006a).
    ('train-call-a', 0x48433C, bytes.fromhex('ff909c000000'), 0x1A0),
    ('train-call-b', 0x48434D, bytes.fromhex('ff909c000000'), 0x1E0),
    # 18:24:26 EIP 0x6a000127, return 0x48437f: code bytes used as [eax+0x84].
    ('train-call-c', 0x484379, bytes.fromhex('ff9084000000'), 0x280),
    # 18:41:42 EIP 0x4183c0: EBX=this=0xfffff95a, read [ebx+0x98].
    ('train-object', 0x4183C0, bytes.fromhex('8b8398000000'), 0x2C0),
    # 18:47:33 EIP 0x49b0e3: ECX=this=0xfffff95a, read [ecx+0x3c].
    ('train-predicate', 0x49B0E3, bytes.fromhex('8b413c83b99608000000'), 0x2E0),
    # Guard the recorded 0x4b0822 fault BEFORE the loop. 0x4b0825 is a target.
    ('train-list', 0x4B081D, bytes.fromhex('8bf98965f0'), 0x300),
)


def build_stubs(base: int) -> bytes:
    # Recorder remains at +0x220..+0x272; the new call guard starts at +0x280.
    buf = bytearray(b'\xcc' * 0x320)

    def put(at: int, blob: bytes) -> None:
        buf[at:at + len(blob)] = blob

    # A: null -> 0x445E3F, else compare and branch like the original
    a = base + 0x00
    put(0x00, b'\x85\xc0'
        + b'\x0f\x84' + rel32(a + 0x08, 0x445E3F)
        + b'\x0f\xbf\x48\x08'
        + b'\x3b\x4d\xe8'
        + b'\x0f\x85' + rel32(a + 0x15, 0x445E3F)
        + b'\xe9' + rel32(a + 0x1A, 0x445EA1))
    # B
    b = base + 0x20
    put(0x20, b'\x85\xc0'
        + b'\x0f\x84' + rel32(b + 0x08, 0x445F79)
        + b'\x0f\xbf\x48\x08'
        + b'\x3b\x4d\xe8'
        + b'\x0f\x85' + rel32(b + 0x15, 0x445F79)
        + b'\xe9' + rel32(b + 0x1A, 0x445FEC))
    # C: null skips the city-byte read; otherwise replay lea/push/mov and enter the call
    cva = base + 0x40
    put(0x40, b'\x85\xc0'
        + b'\x0f\x84' + rel32(cva + 0x08, 0x45C518)
        + b'\x8d\x4d\xe0'
        + b'\x51'
        + b'\x8b\xc8'
        + b'\xe9' + rel32(cva + 0x13, 0x45C4E7))
    # D
    d = base + 0x60
    put(0x60, b'\x85\xc0'
        + b'\x0f\x84' + rel32(d + 0x08, 0x44D768)
        + b'\x89\x45\xec'
        + b'\x8b\xcb'
        + b'\x0f\xbf\x40\x08'
        + b'\xe9' + rel32(d + 0x16, 0x44D69D))
    # E
    e = base + 0x80
    put(0x80, b'\x85\xc0'
        + b'\x0f\x84' + rel32(e + 0x08, 0x49B822)
        + b'\x80\xb8\x83\x00\x00\x00\x02'
        + b'\x0f\x85' + rel32(e + 0x15, 0x49B82B)
        + b'\xe9' + rel32(e + 0x1A, 0x49B822))
    # F: city lookup already returned in eax. Null skips the whole general.
    f = base + 0xA0
    put(0xA0, b'\x85\xc0'
        + b'\x0f\x84' + rel32(f + 0x08, 0x469278)
        + b'\x68\x70\x33\x53\x00'
        + b'\xe9' + rel32(f + 0x12, 0x469250))
    # G: mov eax,[esp+4] already ran. Null skips both stores and returns.
    g = base + 0xC0
    put(0xC0, b'\x85\xc0'
        + b'\x0f\x84' + rel32(g + 0x08, 0x4858EC)
        + b'\xc7\x00\x0d\x00\x00\x00'
        + b'\xc7\x40\x04\x14\x00\x00\x00'
        + b'\xe9' + rel32(g + 0x1A, 0x4858EC))
    # H: word result. Null returns 0. -1 used to fall into a later divide and exit the client.
    h = base + 0xE0
    put(0xE0, b'\x85\xc0'
        + b'\x0f\x84' + rel32(h + 0x08, h + 0x10)
        + b'\x0f\xb7\x00'
        + b'\xe9' + rel32(h + 0x10, 0x4AE384)
        + b'\x31\xc0\x90'
        + b'\xe9' + rel32(h + 0x18, 0x4AE384))
    # I: byte result. Replay the call, then the same null return.
    i = base + 0x100
    put(0x100, b'\xff\x74\x24\x08'
        + b'\x8b\x01'
        + b'\xff\x74\x24\x08'
        + b'\xff\x50\x1c'
        + b'\x85\xc0'
        + b'\x0f\x84' + rel32(i + 0x15, i + 0x1D)
        + b'\x0f\xb6\x00'
        + b'\xe9' + rel32(i + 0x1D, 0x4AE384)
        + b'\x31\xc0\x90'
        + b'\xe9' + rel32(i + 0x25, 0x4AE384))
    # J: product of the two counts. Zero skips the divide and stores 0.
    j = base + 0x140
    put(0x140, b'\x8b\x4e\x3a'
        + b'\x0f\xaf\x4e\x42'
        + b'\x85\xc9'
        + b'\x74\x05'
        + b'\x99'
        + b'\xf7\xf9'
        + b'\xeb\x02'
        + b'\x31\xc0'
        + b'\xe9' + rel32(j + 0x17, 0x42DBAC))
    # K: second count. Zero skips the divide and stores 0.
    k = base + 0x160
    put(0x160, b'\x83\x7e\x46\x00'
        + b'\x74\x08'
        + b'\x99'
        + b'\xf7\x7e\x46'
        + b'\x8b\xce'
        + b'\xeb\x04'
        + b'\x31\xc0'
        + b'\x8b\xce'
        + b'\xe9' + rel32(k + 0x17, 0x42DBBC))
    # L: training-step divisor. Zero stores a zero quotient and continues.
    m = base + 0x180
    put(0x180, b'\x8b\xc8'
        + b'\x8b\x45\x08'
        + b'\x2b\x45\x0c'
        + b'\x85\xc9'
        + b'\x74\x05'
        + b'\x99'
        + b'\xf7\xf9'
        + b'\xeb\x02'
        + b'\x31\xc0'
        + b'\xe9' + rel32(m + 0x18, 0x48432C))

    def guarded_call(at: int, ret: int, slot: int = 0x9C, stack_args: int = 0) -> bytes:
        # Skip invalid vtables/targets, return 0 and clean callee-owned arguments.
        slot_bytes = struct.pack('<I', slot)
        blob = bytearray(
            b'\x3d\x00\xb0\x4f\x00'          # cmp eax, 0x4FB000
            + b'\x72\x00'                    # jb skip
            + b'\x3d\x00\x60\x51\x00'        # cmp eax, 0x516000
            + b'\x73\x00'                    # jae skip
            + b'\x52'                        # push edx
            + b'\x8b\x90' + slot_bytes        # mov edx, [eax+slot]
            + b'\x81\xfa\x00\x10\x40\x00'    # cmp edx, 0x401000
            + b'\x72\x00'                    # jb restore
            + b'\x81\xfa\x00\xa0\x4f\x00'    # cmp edx, 0x4FA000
            + b'\x73\x00'                    # jae restore
            + b'\x5a'                        # pop edx
            + b'\xff\x90' + slot_bytes        # call [eax+slot]
            + b'\xe9\x00\x00\x00\x00'        # jmp ret
            + b'\x5a'                        # pop edx
            + b'\x31\xc0'                    # skip: xor eax, eax
            + (b'\x83\xc4' + bytes([stack_args]) if stack_args else b'')
            + b'\xe9\x00\x00\x00\x00'        # jmp ret
        )
        # Only write branch operands. The former blob[5] assignment overwrote
        # the first JB opcode with SUB AL,0x2b, corrupting the vtable address.
        # 0: cmp (5) = 5
        # 5: jb rel8 (2) = 7
        # 7: cmp (5) = 12
        # 12: jae rel8 (2) = 14
        # 14: push (1) = 15
        # 15: mov (6) = 21
        # 21: cmp (6) = 27
        # 27: jb rel8 (2) = 29
        # 29: cmp (6) = 35
        # 35: jae rel8 (2) = 37
        # 37: pop (1) = 38
        # 38: call (6) = 44
        # 44: jmp rel32 (5) = 49
        # 49: pop (1) = 50
        # 50: zero return; optional argument cleanup; final jmp ret
        assert len(blob) == 57 + (3 if stack_args else 0)
        skip = 50
        restore = 49
        blob[6] = skip - 7
        blob[13] = skip - 14
        blob[28] = restore - 29
        blob[36] = restore - 37
        struct.pack_into('<i', blob, 45, ret - (at + 49))
        struct.pack_into('<i', blob, len(blob) - 4, ret - (at + len(blob)))
        return bytes(blob)

    put(0x1A0, guarded_call(base + 0x1A0, 0x484342))
    put(0x1E0, guarded_call(base + 0x1E0, 0x484353))
    put(0x280, guarded_call(base + 0x280, 0x48437F, slot=0x84, stack_args=4))
    # P: prologue already saved EBX/ESI/EDI and allocated the frame.
    # Invalid this must use the original epilogue, not a bare ret.
    p = base + 0x2C0
    put(0x2C0, b'\x85\xdb'
        + b'\x0f\x8e' + rel32(p + 0x08, p + 0x13)
        + b'\x8b\x83\x98\x00\x00\x00'
        + b'\xe9' + rel32(p + 0x13, 0x4183C6)
        + b'\x31\xc0'
        + b'\xe9' + rel32(p + 0x1A, 0x4184BB))
    # Q: no prologue or arguments. Preserve the original CMP flags for its JE.
    q = base + 0x2E0
    put(0x2E0, b'\x85\xc9'
        + b'\x0f\x8e' + rel32(q + 0x08, 0x49B100)
        + bytes.fromhex('8b413c83b99608000000')
        + b'\xe9' + rel32(q + 0x17, 0x49B0ED))
    # R: replay mov edi,ecx / mov [ebp-0x10],esp before checking this.
    # Never cover 0x4b0825: three native loop backs enter that TEST directly.
    # Invalid this uses the existing SEH epilogue to restore fs:[0] and ret 4.
    r = base + 0x300
    put(0x300, bytes.fromhex('8bf98965f0')
        + b'\x85\xff'
        + b'\x0f\x8e' + rel32(r + 0x0D, r + 0x12)
        + b'\xe9' + rel32(r + 0x12, 0x4B0822)
        + b'\x31\xc0'
        + b'\xe9' + rel32(r + 0x19, 0x4B086C))
    return bytes(buf)


def _k32():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
    k.VirtualAllocEx.restype = c.c_void_p
    k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
    k.VirtualProtectEx.restype = w.BOOL
    k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.WriteProcessMemory.restype = w.BOOL
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    k.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]
    k.FlushInstructionCache.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    return k


def read_at(k, h, addr, n):
    buf = c.create_string_buffer(n)
    got = c.c_size_t()
    ok = k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got))
    if not ok or got.value != n:
        return None
    return buf.raw


def write_at(k, h, addr, data):
    old = w.DWORD(0)
    prot = bool(k.VirtualProtectEx(h, c.c_void_p(addr), len(data), PAGE, c.byref(old)))
    got = c.c_size_t()
    raw = c.create_string_buffer(data, len(data))
    ok = bool(k.WriteProcessMemory(h, c.c_void_p(addr), raw, len(data), c.byref(got)) and got.value == len(data))
    if prot:
        tmp = w.DWORD(0)
        k.VirtualProtectEx(h, c.c_void_p(addr), len(data), old.value, c.byref(tmp))
    k.FlushInstructionCache(h, c.c_void_p(addr), len(data))
    back = read_at(k, h, addr, len(data))
    return back == data, back.hex() if back else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pid', type=int, nargs='?')
    ap.add_argument('--clear-lock', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        blob = build_stubs(0x200000)
        assert blob[0:2] == b'\x85\xc0'
        assert len(blob) == 0x320
        f = 0x200000 + 0xA0
        jz = struct.unpack_from('<i', blob, 0xA4)[0]
        jmp = struct.unpack_from('<i', blob, 0xAE)[0]
        assert (f + 0x08 + jz) & 0xFFFFFFFF == 0x469278
        assert (f + 0x12 + jmp) & 0xFFFFFFFF == 0x469250
        assert blob[0xA8:0xAD] == bytes.fromhex('6870335300')
        g = 0x200000 + 0xC0
        jz = struct.unpack_from('<i', blob, 0xC4)[0]
        jmp = struct.unpack_from('<i', blob, 0xD6)[0]
        assert (g + 0x08 + jz) & 0xFFFFFFFF == 0x4858EC
        assert (g + 0x1A + jmp) & 0xFFFFFFFF == 0x4858EC
        h = 0x200000 + 0xE0
        assert (h + 0x10 + struct.unpack_from('<i', blob, 0xEC)[0]) & 0xFFFFFFFF == 0x4AE384
        assert (h + 0x18 + struct.unpack_from('<i', blob, 0xF4)[0]) & 0xFFFFFFFF == 0x4AE384
        i = 0x200000 + 0x100
        assert (i + 0x1D + struct.unpack_from('<i', blob, 0x119)[0]) & 0xFFFFFFFF == 0x4AE384
        assert (i + 0x25 + struct.unpack_from('<i', blob, 0x121)[0]) & 0xFFFFFFFF == 0x4AE384
        j = 0x200000 + 0x140
        assert blob[0x149:0x14B] == b'\x74\x05'
        assert (j + 0x17 + struct.unpack_from('<i', blob, 0x153)[0]) & 0xFFFFFFFF == 0x42DBAC
        k = 0x200000 + 0x160
        assert blob[0x164:0x166] == b'\x74\x08'
        assert (k + 0x17 + struct.unpack_from('<i', blob, 0x173)[0]) & 0xFFFFFFFF == 0x42DBBC
        assert blob[0xF0:0xF3] == b'\x31\xc0\x90'
        m = 0x200000 + 0x180
        assert blob[0x18A:0x18C] == b'\x74\x05'
        assert (m + 0x18 + struct.unpack_from('<i', blob, 0x194)[0]) & 0xFFFFFFFF == 0x48432C
        for off, ret, slot, stack_args in ((0x1A0, 0x484342, 0x9C, 0),
                                           (0x1E0, 0x484353, 0x9C, 0),
                                           (0x280, 0x48437F, 0x84, 4)):
            guard = blob[off:off + 57 + (3 if stack_args else 0)]
            assert guard[5:7] == b'\x72\x2b'  # JB must remain an instruction.
            assert guard[12:14] == b'\x73\x24'
            assert guard[27:29] == b'\x72\x14'
            assert guard[35:37] == b'\x73\x0c'
            assert guard[15:21] == b'\x8b\x90' + struct.pack('<I', slot)
            assert guard[38:44] == b'\xff\x90' + struct.pack('<I', slot)
            assert guard[49:52] == b'\x5a\x31\xc0'
            assert guard[52:-5] == (b'\x83\xc4\x04' if stack_args else b'')
            assert (0x200000 + off + 49 + struct.unpack_from('<i', guard, 45)[0]) & 0xFFFFFFFF == ret
            assert (0x200000 + off + len(guard) + struct.unpack_from('<i', guard, len(guard) - 4)[0]) & 0xFFFFFFFF == ret
        p = 0x200000 + 0x2C0
        assert blob[0x2C0:0x2C8] == bytes.fromhex('85db0f8e0b000000')
        assert blob[0x2C8:0x2CE] == bytes.fromhex('8b8398000000')
        assert blob[0x2D3:0x2D5] == b'\x31\xc0'
        assert (p + 0x13 + struct.unpack_from('<i', blob, 0x2CF)[0]) & 0xFFFFFFFF == 0x4183C6
        assert (p + 0x1A + struct.unpack_from('<i', blob, 0x2D6)[0]) & 0xFFFFFFFF == 0x4184BB
        q = 0x200000 + 0x2E0
        assert blob[0x2E0:0x2E4] == bytes.fromhex('85c90f8e')
        assert blob[0x2E8:0x2F2] == bytes.fromhex('8b413c83b99608000000')
        assert (q + 0x08 + struct.unpack_from('<i', blob, 0x2E4)[0]) & 0xFFFFFFFF == 0x49B100
        assert (q + 0x17 + struct.unpack_from('<i', blob, 0x2F3)[0]) & 0xFFFFFFFF == 0x49B0ED
        r = 0x200000 + 0x300
        assert blob[0x300:0x30D] == bytes.fromhex('8bf98965f085ff0f8e05000000')
        assert blob[0x312:0x314] == b'\x31\xc0'
        assert (r + 0x12 + struct.unpack_from('<i', blob, 0x30E)[0]) & 0xFFFFFFFF == TRAIN_LIST_BODY_AT
        assert (r + 0x19 + struct.unpack_from('<i', blob, 0x315)[0]) & 0xFFFFFFFF == 0x4B086C
        assert next(s[1:3] for s in SITES if s[0] == 'train-list') == (0x4B081D, bytes.fromhex('8bf98965f0'))
        assert TRAIN_LIST_BODY_ORIG == bytes.fromhex('8b770485f6')
        rec = recorder_stub(0x200000)
        assert 0x220 + len(rec) <= 0x280
        assert blob[0x220:0x280] == b'\xcc' * 0x60
        assert RECORDER_AT == 0x56140F
        assert (0x200000 + 0x220 + len(RECORDER_CODES) * 12 + 5
                + struct.unpack_from('<i', rec, len(RECORDER_CODES) * 12 + 1)[0]) & 0xFFFFFFFF == RECORDER_DONE
        assert (0x200000 + 0x220 + len(RECORDER_CODES) * 12 + 10
                + struct.unpack_from('<i', rec, len(RECORDER_CODES) * 12 + 6)[0]) & 0xFFFFFFFF == RECORDER_LOG
        print(json.dumps({'selftest': True, 'sites': len(SITES)}))
        return 0
    if args.pid is None:
        print(json.dumps({'error': 'pid required'}))
        return 1

    k = _k32()
    h = k.OpenProcess(ACCESS, False, args.pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess', 'pid': args.pid, 'err': c.get_last_error()}))
        return 1
    try:
        # An older five-byte hook at 0x4b0822 corrupts the loop target +3.
        # Do not combine it with the relocated guard or treat it as current.
        list_body = read_at(k, h, TRAIN_LIST_BODY_AT, len(TRAIN_LIST_BODY_ORIG))
        if list_body != TRAIN_LIST_BODY_ORIG:
            print(json.dumps({'error': 'list loop bytes are not original; restart via one-click before installing',
                              'pid': args.pid, 'site': hex(TRAIN_LIST_BODY_AT),
                              'hex': list_body.hex() if list_body else None}))
            return 1
        current = {}
        for name, va, orig, _off in SITES:
            got = read_at(k, h, va, len(orig))
            if got is None:
                print(json.dumps({'error': 'read failed', 'site': name, 'pid': args.pid}))
                return 1
            current[name] = got
            if got != orig and not is_hook(got, len(orig)):
                print(json.dumps({'error': 'unexpected bytes', 'site': name, 'pid': args.pid, 'hex': got.hex()}))
                return 1
        if all(is_hook(current[name], len(orig)) for name, _va, orig, _off in SITES):
            print(json.dumps({'pid': args.pid, 'already': True, 'sites': len(SITES)}))
            return 0
        cave = k.VirtualAllocEx(h, None, 0x1000, MEM, PAGE)
        if not cave:
            print(json.dumps({'error': 'VirtualAllocEx', 'pid': args.pid, 'err': c.get_last_error()}))
            return 1
        cave = int(cave)
        blob = build_stubs(cave)
        ok, back = write_at(k, h, cave, blob)
        if not ok:
            print(json.dumps({'error': 'cave mismatch', 'pid': args.pid, 'back': back}))
            return 1
        patched = []
        for name, va, orig, off in SITES:
            if is_hook(current[name], len(orig)):
                patched.append({'site': name, 'skipped': True})
                continue
            stub = hook_bytes(va, cave + off, len(orig))
            ok, back = write_at(k, h, va, stub)
            patched.append({'site': name, 'va': hex(va), 'ok': ok, 'wrote': stub.hex(), 'back': back})
            if not ok:
                print(json.dumps({'error': 'site mismatch', 'pid': args.pid, 'patched': patched}))
                return 1
        rec = recorder_stub(cave)
        got = read_at(k, h, RECORDER_AT, len(RECORDER_OLD))
        if got == RECORDER_OLD:
            ok_rec, _back = write_at(k, h, cave + 0x220, rec)
            hooked, hook_back = (False, None)
            if ok_rec:
                hooked, hook_back = write_at(k, h, RECORDER_AT, hook_bytes(RECORDER_AT, cave + 0x220, len(RECORDER_OLD)))
            recorder = {'ok': bool(ok_rec and hooked), 'back': hook_back}
        elif got and is_hook(got, len(RECORDER_OLD)):
            recorder = {'ok': True, 'already': True}
        else:
            recorder = {'ok': False, 'hex': got.hex() if got else None}
        out = {'pid': args.pid, 'cave': hex(cave), 'patched': patched, 'recorder': recorder, 'ok': True}
        if args.clear_lock:
            lock = read_at(k, h, LOCK_VA, 4)
            before = struct.unpack('<I', lock)[0] if lock else None
            ok, back = write_at(k, h, LOCK_VA, struct.pack('<I', 0))
            out['lock_before'] = before
            out['lock_write_ok'] = ok
            out['lock_back'] = back
        print(json.dumps(out, ensure_ascii=False))
        return 0
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    sys.exit(main() or 0)
