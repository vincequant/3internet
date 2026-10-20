"""P62 read-only netobj probe (run under Wine py32 in the ghost prefix).

Reads the Koeinm session object fields that decide what a D8 send would do:
  netobj+0x0148  is_host
  netobj+0x43b8  pointer to the member-row array
  netobj+0x43bc  member row count
  netobj+0x84a8  native pre-start state
  row0.id = *(netobj+0x43b8)          (host row in a member session)
  row1.id = *(netobj+0x43b8 + 0x164)  (what 0x4c80 returns for a member)
and computes the 0x4c80 result exactly as the DLL does:
  if is_host: row0.id
  elif rowcount > 1: row1.id
  else: 0

Read-only: OpenProcess with VM_READ|QUERY_INFORMATION only, no writes.
Usage: python.exe p62_netobj_probe.py <sanpk-wine-pid>
"""
from __future__ import annotations

import ctypes as c
import json
import sys
from ctypes import wintypes as w

NETOBJ_RVA = 0x12170
ROW_STRIDE = 0x164


def _win():
    return c, w, c.WinDLL('kernel32', use_last_error=True)


def find_module(pid, name):
    c_, w_, k = _win()
    h = k.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return None
    try:
        psapi = c_.WinDLL('psapi', use_last_error=True)
        psapi.EnumProcessModules.argtypes = [w_.HANDLE, c_.c_void_p, w_.DWORD, c_.POINTER(w_.DWORD)]
        psapi.GetModuleBaseNameW.argtypes = [w_.HANDLE, c_.c_void_p, w_.LPWSTR, w_.DWORD]

        class ModInfo(c_.Structure):
            _fields_ = [('lpBaseOfDll', c_.c_void_p), ('SizeOfImage', w_.DWORD),
                        ('EntryPoint', c_.c_void_p)]

        psapi.GetModuleInformation.argtypes = [w_.HANDLE, c_.c_void_p,
                                               c_.POINTER(ModInfo), w_.DWORD]
        arr = (c_.c_void_p * 1024)()
        need = w_.DWORD(0)
        if not psapi.EnumProcessModules(h, arr, c_.sizeof(arr), c_.byref(need)):
            return None
        buf = c_.create_unicode_buffer(260)
        for i in range(min(need.value // c_.sizeof(c_.c_void_p), 1024)):
            if not psapi.GetModuleBaseNameW(h, arr[i], buf, 260):
                continue
            if buf.value.lower() == name.lower():
                mi = ModInfo()
                if psapi.GetModuleInformation(h, arr[i], c_.byref(mi), c_.sizeof(mi)):
                    return {'base': int(mi.lpBaseOfDll or 0), 'size': int(mi.SizeOfImage)}
        return None
    finally:
        k.CloseHandle(h)


def read32(k, h, addr):
    buf = c.create_string_buffer(4)
    got = c.c_size_t()
    if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, 4, c.byref(got)) or got.value != 4:
        return None
    return int.from_bytes(buf.raw, 'little')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: p62_netobj_probe.py <sanpk-wine-pid>')
    pid = int(sys.argv[1])
    c_, w_, k = _win()
    mod = find_module(pid, 'Koeinm.dll')
    if not mod:
        print(json.dumps({'ok': False, 'error': 'koeinm_not_found', 'pid': pid}))
        return 2
    h = k.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        print(json.dumps({'ok': False, 'error': 'openprocess_%d' % c_.get_last_error(),
                          'pid': pid}))
        return 2
    try:
        netobj = mod['base'] + NETOBJ_RVA
        out = {'ok': True, 'pid': pid, 'koeinm_base': hex(mod['base']),
               'koeinm_size': hex(mod['size']), 'netobj': hex(netobj)}
        is_host = read32(k, h, netobj + 0x0148)
        sync_a = read32(k, h, netobj + 0x84C4)
        sync_b = read32(k, h, netobj + 0x84C8)
        q_n = read32(k, h, netobj + 0x84D4)
        q_ptr = read32(k, h, netobj + 0x84D0)
        state = read32(k, h, netobj + 0x84A8)
        rows_ptr = read32(k, h, netobj + 0x43B8)
        rows_n = read32(k, h, netobj + 0x43BC)
        out.update({'is_host': is_host, 'state_84a8': state,
                    'sync_84c4': sync_a, 'sync_84c8': sync_b,
                    'queue_count_84d4': q_n, 'queue_ptr_84d0': (hex(q_ptr) if q_ptr else None),
                    'rows_ptr': (hex(rows_ptr) if rows_ptr else None), 'rows_n': rows_n})
        row_ids = []
        if rows_ptr and rows_n and 0 < rows_n <= 64:
            for i in range(min(int(rows_n), 8)):
                rid = read32(k, h, rows_ptr + i * ROW_STRIDE)
                row_ids.append(rid)
        out['row_ids'] = row_ids
        q = []
        if q_ptr and q_n and 0 < q_n <= 32:
            for i in range(int(q_n)):
                q.append(read32(k, h, q_ptr + i * 4))
        out['queue_ids'] = q
        if is_host:
            out['gethost_4c80'] = row_ids[0] if row_ids else 0
        elif rows_n is not None and rows_n > 1 and len(row_ids) > 1:
            out['gethost_4c80'] = row_ids[1]
        else:
            out['gethost_4c80'] = 0
        print(json.dumps(out, ensure_ascii=False))
        return 0
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    raise SystemExit(main() or 0)
