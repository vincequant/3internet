"""P24a (read-only): dump L+0a/L+0e CString contents for live host rows.
Usage: p24_rowdetail.py <SANPK_PID> <row0_base_hex> -- finds rows by scanning
the eight 0x87-stride rows from row0 and prints id/w4/L+0a/L+0e per row.
"""
import json, struct, sys
from pathlib import Path
BRIDGE = Path(r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge')
sys.path.insert(0, str(BRIDGE))
import os
os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
from probe import Memory  # noqa: E402


def dec(b):
    if b is None:
        return None
    return b.split(b'\x00', 1)[0].decode('gbk', 'replace')


def main():
    pid = int(sys.argv[1])
    row0 = int(sys.argv[2], 16)
    m = Memory(pid)
    m.load()
    rows = []
    try:
        for i in range(8):
            base = row0 + i * 0x87
            buf = m.read(base, 0x20)
            if buf is None:
                rows.append({'i': i, 'error': 'read_failed'})
                continue
            rid = struct.unpack_from('<I', buf, 6)[0]
            w4 = struct.unpack_from('<H', buf, 4)[0]
            a_ptr = struct.unpack_from('<I', buf, 0x0a)[0]
            e_ptr = struct.unpack_from('<I', buf, 0x0e)[0]
            rows.append({
                'i': i, 'id': rid, 'w4': w4,
                'text_a': dec(m.read(a_ptr, 64)) if a_ptr else None,
                'name_e': dec(m.read(e_ptr, 64)) if e_ptr else None,
            })
    finally:
        m.close()
    print(json.dumps({'row0': hex(row0), 'rows': rows, 'readonly': True},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
