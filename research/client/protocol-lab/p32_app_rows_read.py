"""P32 read-only all-candidate app rows, including paired L/P (+0x862).
No first-anchor selection and no V/D mixed gates.
"""
import time
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
    # Preserve every plausible row0; strong candidates must not hide L or P.
    for base in list(blocks):
        for companion in (base-0x862, base+0x862):
            b = m.read(companion, ROW) if companion > 0 else None
            if b and struct.unpack_from('<I', b, 6)[0] and read_cstr(m, struct.unpack_from('<I', b, 14)[0]) == HOST_NAME:
                if companion not in blocks:
                    blocks.append(companion)
    blocks.sort()
    out['candidate_row0'] = [hex(b) for b in blocks]
    if not blocks:
        out['abort'] = 'no_adjacent_block'
        print(json.dumps(out, ensure_ascii=False))
        return
    tables = []
    for row0 in blocks:
        rows = []
        for i in range(8):
            base = row0+i*ROW
            buf = m.read(base, ROW)
            if not buf or len(buf) != ROW:
                rows.append({'i': i, 'error': 'read_failed'})
                continue
            text = read_cstr(m, struct.unpack_from('<I', buf, 0x0a)[0])
            name = read_cstr(m, struct.unpack_from('<I', buf, 0x0e)[0])
            row = {'i': i, 'base': hex(base), 'id': struct.unpack_from('<I', buf, 6)[0],
                   'w4': struct.unpack_from('<H', buf, 4)[0], 'name': name,
                   'machine_name': text, 'state': struct.unpack_from('<I', buf, 0x42)[0],
                   'monarch': struct.unpack_from('<i', buf, 0x46)[0],
                   'd12': struct.unpack_from('<I', buf, 0x12)[0],
                   'd7f': struct.unpack_from('<I', buf, 0x7f)[0], 'raw_hex': buf.hex()}
            row['pending_2723'] = row['state'] == 0 and row['id'] != 0 and not name
            rows.append(row)
        label = ('L_pair_lower' if row0+0x862 in blocks else
                 'P_pair_upper' if row0-0x862 in blocks else 'unpaired_unknown')
        tables.append({'row0': hex(row0), 'table_hypothesis': label,
                       'basis': 'D+b4 vs D+916 static spacing; candidate, not live-stage proof',
                       'rows': rows})
    out.update({'wall': time.time(), 'tables': tables, 'selected_table': None})
    print(json.dumps(out, ensure_ascii=False))
    m.close()


if __name__ == '__main__':
    main()
