"""Offline PE resource inventory and bounded source evidence; never executes PE."""
import json
from pathlib import Path
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'protocol-archive'))
from sim.artifact import PE


def resources(pe):
    base = pe.offset(pe.directories[2][0])
    leaves = []

    def walk(off, keys):
        count = sum(struct.unpack_from('<HH', pe.data, base+off+12))
        for i in range(count):
            key, child = struct.unpack_from('<II', pe.data, base+off+16+i*8)
            if key & 0x80000000:
                p = base+(key & 0x7fffffff)
                size = pe.u16(p)
                key = pe.data[p+2:p+2+size*2].decode('utf-16le')
            if child & 0x80000000:
                walk(child & 0x7fffffff, keys+[key])
            else:
                rva, size, cp, _ = struct.unpack_from('<IIII', pe.data, base+child)
                pos = pe.offset(rva)
                leaves.append({'keys': keys+[key], 'rva': rva, 'offset': pos,
                               'size': size, 'codepage': cp})
    walk(0, [])
    return leaves


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos+n > len(self.data):
            raise ValueError('resource_truncated')
        raw = self.data[self.pos:self.pos+n]
        self.pos += n
        return raw

    def word(self):
        return struct.unpack('<H', self.take(2))[0]

    def dword(self):
        return struct.unpack('<I', self.take(4))[0]

    def align(self):
        self.pos = (self.pos+3)//4*4

    def string(self, first=None):
        words = [] if first is None else [first]
        while not words or words[-1] != 0:
            words.append(self.word())
        return b''.join(struct.pack('<H', n) for n in words[:-1]).decode('utf-16le')

    def field(self):
        first = self.word()
        return {'ordinal': self.word()} if first == 65535 else self.string(first)


def dialog(data):
    r = Reader(data)
    extended = data[:4] == b'\x01\x00\xff\xff'
    if extended:
        r.take(8)
        exstyle, style, count = r.dword(), r.dword(), r.word()
    else:
        style, exstyle, count = r.dword(), r.dword(), r.word()
    r.take(8)
    menu, cls, title = r.field(), r.field(), r.field()
    if style & 0x40:
        r.word()
        if extended:
            r.take(4)
        font = r.string()
    controls = []
    for _ in range(count):
        r.align()
        if extended:
            r.dword()
            ex, st = r.dword(), r.dword()
        else:
            st, ex = r.dword(), r.dword()
        r.take(8)
        ident = r.dword() if extended else r.word()
        control_class, text = r.field(), r.field()
        extra = r.word()
        if extra:
            r.take(extra-2)
        controls.append({'id': ident, 'class': control_class, 'text': text})
    return {'title': title, 'controls': controls}


def menu(data):
    r = Reader(data)
    version, extra = r.word(), r.word()
    if version != 0:
        raise ValueError('menuex_unimplemented')
    r.take(extra)
    def items():
        out = []
        for _ in range(1024):
            flags = r.word()
            ident = None if flags & 16 else r.word()
            item = {'id': ident, 'flags': flags, 'text': r.string()}
            if flags & 16:
                item['children'] = items()
            out.append(item)
            if flags & 128:
                return out
        raise ValueError('menu_bound')
    return items()


def inventory(path):
    pe = PE(path)
    out = []
    for leaf in resources(pe):
        if leaf['keys'][0] not in (4, 5, 6):
            continue
        raw = pe.data[leaf['offset']:leaf['offset']+leaf['size']]
        row = dict(leaf)
        try:
            if leaf['keys'][0] == 6:
                r = Reader(raw)
                row['strings'] = [{'id': (leaf['keys'][1]-1)*16+i,
                    'text': r.take(r.word()*2).decode('utf-16le')} for i in range(16)]
            else:
                row['content'] = dialog(raw) if leaf['keys'][0] == 5 else menu(raw)
        except (ValueError, struct.error, UnicodeError) as e:
            row['unknown'] = str(e)
        out.append(row)
    return out


if __name__ == '__main__':
    print(json.dumps(inventory(sys.argv[1]), ensure_ascii=False, indent=2))
