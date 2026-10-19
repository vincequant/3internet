"""P19 app-row reader (read-only): dump the host SANPK's 8 application rows.

Static ground truth (m7-start-preconditions.md, m7-host-registration.md):
- Start entries 464b49/464fc8 show resource 2723 when any row with
  DWORD L+42==0 AND DWORD L+6!=0 has BYTE[*CString(L+0e)]==0 (empty name).
- Row layout: L+4 WORD, L+6 DWORD id, L+0e char* (CString buffer), L+42 DWORD
  state, L+46 DWORD (monarch decision), L+7a char* extra, row stride 0x87.
- Rows live at L_i = D+0xb4+i*0x87; row 0 is the local host row
  (4465d7/446729 init D+c2), members fill rows by first-empty scan order.
- Branch 1 of the start gate needs D+0x88d != 0 (script chosen).

Method (fully dynamic — member ids change on every ghost relogin and every
room rebuild): locate the host name's CString buffer by raw GBK bytes, find
rows referencing it through the char* at L+0x0e, validate row shape (nonzero
id, w4 in {1,2}, state<=2), then require at least one rows-1..7 entry that
looks like a real member (nonzero id with non-empty name). Never writes.

Usage (wine python32, from the vkquant Mac): p19_app_rows_read.py <SANPK_PID>
"""
import json
import struct
import sys
from pathlib import Path

import os
BRIDGE = Path(os.environ.get('SGI_BRIDGE_Z', r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge'))
sys.path.insert(0, str(BRIDGE))
import os
os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
from probe import Memory  # noqa: E402

ROW = 0x87
HOST_NAME = os.environ.get('SGI_HOST_NAME', '丁满')


def dec(b):
    if b is None:
        return None
    return b.split(b'\x00', 1)[0].decode('gbk', 'replace')


def read_cstr(m, ptr, cap=96):
    if not ptr:
        return None
    raw = m.read(ptr, cap)
    return dec(raw) if raw is not None else None


def main():
    pid = int(sys.argv[1])
    m = Memory(pid)
    m.load()
    diag = {'regions': len(m.regions), 'segments': len(m.segments),
            'scan_mb': round(sum(len(b) for _, b in m.segments) / 1e6, 1),
            'scan_s': round(m.scan_s, 1), 'failures': len(m.failures)}
    out = {'pid': pid, 'diag': diag, 'readonly': True}
    # dynamic discovery: find the host name's CString buffers by raw bytes,
    # then rows referencing them via the char* field at L+0x0e
    pat = HOST_NAME.encode('gbk') + b'\x00'
    str_hits = m.find(pat, limit=200)
    out['name_hits'] = len(str_hits)
    blocks = []
    for s in str_hits:
        for p in m.find(struct.pack('<I', s), limit=100):
            base = p - 0x0e
            if base in blocks:
                continue
            buf = m.read(base, 0x50)
            if buf is None:
                continue
            if struct.unpack_from('<I', buf, 0x0e)[0] != s:
                continue
            if struct.unpack_from('<I', buf, 6)[0] == 0:
                continue
            if struct.unpack_from('<H', buf, 4)[0] not in (1, 2):
                continue
            if struct.unpack_from('<I', buf, 0x42)[0] > 2:
                continue
            blocks.append(base)
    # strong validation (dynamic): rows 1..7 must contain at least one
    # real member row (nonzero id with non-empty name)
    strong = []
    for base in blocks:
        for i in range(1, 8):
            rowbuf = m.read(base + i * ROW, 0x50)
            if rowbuf is None:
                continue
            rid = struct.unpack_from('<I', rowbuf, 6)[0]
            nptr = struct.unpack_from('<I', rowbuf, 0x0e)[0]
            if rid != 0 and read_cstr(m, nptr, 8):
                strong.append(base)
                break
    out['strong_row0'] = [hex(b) for b in strong]
    blocks = strong or blocks
    out['candidate_row0'] = [hex(b) for b in blocks]
    if not blocks:
        out['abort'] = 'no_adjacent_block'
        print(json.dumps(out, ensure_ascii=False))
        return
    row0 = blocks[0]
    rows = []
    for i in range(8):
        base = row0 + i * ROW
        buf = m.read(base, ROW)
        if buf is None:
            rows.append({'i': i, 'error': 'read_failed'})
            continue
        nameptr = struct.unpack_from('<I', buf, 0x0e)[0]
        name = read_cstr(m, nameptr)
        row = {
            'i': i, 'base': hex(base),
            'id': struct.unpack_from('<I', buf, 6)[0],
            'w4': struct.unpack_from('<H', buf, 4)[0],
            'name_ptr': hex(nameptr), 'name': name,
            'state': struct.unpack_from('<I', buf, 0x42)[0],
            'monarch': struct.unpack_from('<i', buf, 0x46)[0],
            'extra_ptr': hex(struct.unpack_from('<I', buf, 0x7a)[0]),
            'clamp_7e': buf[0x7e],
        }
        row['pending_2723'] = bool(
            row['state'] == 0 and row['id'] != 0
            and (name is None or len(name) == 0))
        rows.append(row)
    d = row0 - 0xb4
    gates = {}
    for off, label in ((0x88d, 'script_selected_byte_88d'),
                       (0x8e8, 'd_8e8'), (0x8ec, 'd_8ec'),
                       (0x8a8, 'd_8a8'), (0x8f0, 'd_8f0')):
        b = m.read(d + off, 4)
        gates[label] = struct.unpack('<I', b)[0] if b else None
    out.update({'d_base': hex(d), 'gates': gates, 'rows': rows})
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
