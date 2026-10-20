"""Native dynamic tile fields use fresh capture data and preserve static maps."""
import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT.parent / 'protocol-lab' / '_p60_construction_grid.py'
if not PATH.is_file():
    PATH = ROOT / 'lab-tools' / '_p60_construction_grid.py'
spec = importlib.util.spec_from_file_location('construction_grid_test_module', PATH)
grid_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid_module)


class FakeCollector:
    def __init__(self):
        self.core = 0x100000
        self.static = {'width': 2, 'height': 3, 'types': '000102030405'}
        self.fields = {0x30000 + 32*i: (-1, -1) for i in range(6)}
        self.bad = set()

    def terrain_grid(self):
        return self.static

    def read(self, address, size):
        if address == self.core + 0x5fc:
            header = bytearray(28)
            struct.pack_into('<I', header, 4, 0x20000)
            struct.pack_into('<II', header, 20, 2, 3)
            return bytes(header)
        if address == 0x20000:
            return struct.pack('<6I', *self.fields)
        pointer = address - 12
        if pointer in self.bad:
            raise RuntimeError('unreadable tile')
        return struct.pack('<hh', *self.fields[pointer])


class ConstructionGridTests(unittest.TestCase):
    def test_column_major_signed_fields_preserve_static_terrain(self):
        collector = grid_module.with_construction_grid(FakeCollector)()
        collector.fields[0x30000+32*4] = (5, 7)
        data = collector.terrain_grid()
        kinds = bytes.fromhex(data['object_kinds_s16le'])
        controls = bytes.fromhex(data['control_forces_s16le'])
        self.assertEqual(struct.unpack('<6h', kinds), (-1,-1,-1,-1,7,-1))
        self.assertEqual(struct.unpack_from('<h', controls, 8)[0], 5)
        self.assertEqual(data['layout'], 'column-major')
        self.assertEqual(collector.static, {'width':2,'height':3,'types':'000102030405'})

    def test_dynamic_fields_are_not_static_cached_and_unread_is_not_empty(self):
        collector = grid_module.with_construction_grid(FakeCollector)()
        first = collector.terrain_grid()
        collector.fields[0x30000] = (16, 2)
        collector.bad.add(0x30000+32)
        second = collector.terrain_grid()
        self.assertEqual(struct.unpack_from('<h', bytes.fromhex(first['object_kinds_s16le']))[0], -1)
        self.assertEqual(struct.unpack('<6h', bytes.fromhex(second['object_kinds_s16le']))[:2], (2, -32768))
        self.assertEqual(second['construction_unread_cells'], 1)


if __name__ == '__main__':
    unittest.main()
