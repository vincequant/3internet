"""Meaningful read-only decoder, identity, list-integrity and hit-model tests."""
import json
from pathlib import Path
import struct
import unittest

from p53_unit_data import (capture_map, context, hit_units, inspect_unit,
                          panel_text, native_hit, world_to_pixel, UNIT_TYPES)
from p53_ui_control import desired_action, mode_for

CORE, DOC, VIEW, UNIT = 0x301000, 0x301000-0x912, 0x304000, 0x309000


class Fixture:
    """Explicit synthetic address space; never used as live game data."""
    def __init__(self):
        self.regions = {0x300000: bytearray(0x40000), 0x530000: bytearray(0x10000)}
        self.next = 0x310000; self.reads = 0; self.mutate = None
        self.put(0x53bb30, CORE); self.put(0x53b930, VIEW)
        self.put(CORE, 0x5053c0); self.put(DOC, 0x504d40)
        self.put(VIEW, 0x50b730); self.put(VIEW+0x3c, DOC); self.put(VIEW+0x1c, 123)
        self.put(DOC+0x68, 2); self.write(DOC+0xdea, struct.pack('<h', 3))
        self.write(DOC+0xf22, struct.pack('<4i', 101, 202, 64, 32))
        self.write(VIEW+0x54, struct.pack('<2i', 120, 210))
        self.write(VIEW+0x64, struct.pack('<2i', 800, 600))
        raw = bytearray(168)
        struct.pack_into('<IhhHH', raw, 0, 0x508878, 8, 17, 1, 42)
        struct.pack_into('<3H', raw, 0xf, 17, 65535, 19)
        struct.pack_into('<II', raw, 0x15, 12345, 67890)
        raw[0x1d], raw[0x1e], raw[0x20], raw[0x29], raw[0xd] = 91, 72, 6, 95, 1
        struct.pack_into('<I', raw, 0x5e, 0x12345678)
        struct.pack_into('<H', raw, 0x7e, 0x16)
        self.write(UNIT, raw); self.list(0x534, [UNIT])
        trap = self.alloc(24); self.write(trap, struct.pack('<IhhHH12x', 0x50a260, 7, 9, 1, 91))
        self.list(0x5b4, [trap])
        general = self.alloc(96); raw = bytearray(96)
        struct.pack_into('<I', raw, 0, 0x5056f0); struct.pack_into('<H', raw, 10, 17)
        for off, name in ((12, '测'), (16, '试'), (20, '合成')):
            struct.pack_into('<I', raw, off, self.string(name))
        struct.pack_into('<H', raw, 0x21, 2); struct.pack_into('<H', raw, 35, 3000)
        raw[37:42] = bytes((91, 82, 73, 64, 55))
        struct.pack_into('<I', raw, 0x2a, 0x1234); struct.pack_into('<h', raw, 0x34, 8)
        self.write(general, raw); self.general = general; self.list(0x514, [general])
        lord = self.alloc(273); self.put(lord, 0x506660)
        self.write(lord+8, struct.pack('<H', 1)); self.put(lord+10, self.string('合成敌方'))
        self.list(0x4f4, [lord])
        city = self.alloc(81); self.put(city, 0x503688)
        self.write(city+10, struct.pack('<H', 8)); self.put(city+12, self.string('合成城'))
        self.list(0x554, [city])

    def alloc(self, size):
        at = self.next; self.next += (size+15)&~15; return at

    def string(self, value):
        raw = value.encode('gbk')+b'\0'; at = self.alloc(max(112, len(raw)))
        self.write(at, raw); return at

    def write(self, address, raw):
        for base, region in self.regions.items():
            if base <= address and address+len(raw) <= base+len(region):
                region[address-base:address-base+len(raw)] = raw; return
        raise ValueError('fixture unmapped write')

    def put(self, address, value): self.write(address, struct.pack('<I', value))

    def read(self, address, size):
        self.reads += 1
        if self.mutate: self.mutate(self, address, size)
        for base, region in self.regions.items():
            if base <= address and address+size <= base+len(region):
                return bytes(region[address-base:address-base+size])
        return None

    def list(self, offset, objects):
        nodes = [self.alloc(12) for _ in objects]
        for index, (node, obj) in enumerate(zip(nodes, objects)):
            self.write(node, struct.pack('<III', nodes[index+1] if index+1<len(nodes) else 0,
                                        nodes[index-1] if index else 0, obj))
        self.write(CORE+offset+4, struct.pack('<III', nodes[0] if nodes else 0,
                                           nodes[-1] if nodes else 0, len(nodes)))
        return nodes


class DataTests(unittest.TestCase):
    def test_enemy_unit_trap_and_three_general_slots_without_any_write(self):
        f = Fixture(); before = {a: bytes(b) for a, b in f.regions.items()}
        snap = capture_map(f.read); self.assertEqual(len(snap['traps']), 1)
        row = inspect_unit(f.read, snap, snap['units'][0])
        self.assertEqual(row['unit']['soldiers_candidate'], 12345)
        self.assertEqual(row['unit']['rice_candidate'], 67890)
        self.assertEqual(row['unit']['owner_name'], '合成敌方')
        self.assertEqual(row['unit']['general_ids'], [17, None, 19])
        self.assertEqual(row['generals'][0]['attributes'], dict(zip(('统率','武力','智力','政治','魅力'), (91,82,73,64,55))))
        self.assertEqual(row['generals'][0]['city_name'], '合成城')
        self.assertEqual(row['missing_general_ids'], [19])
        self.assertEqual(before, {a: bytes(b) for a, b in f.regions.items()})
        self.assertIn('未定', panel_text(row)); self.assertIn('未捕获此武将', panel_text(row))
        self.assertNotIn('士气 91', panel_text(row))

    def test_all_12_classes_and_colocated_units_are_retained(self):
        f = Fixture(); addresses = []
        raw = bytearray(f.read(UNIT, 168))
        for index, vt in enumerate(UNIT_TYPES):
            a = f.alloc(168); struct.pack_into('<I', raw, 0, vt)
            struct.pack_into('<H', raw, 10, 100+index); f.write(a, raw); addresses.append(a)
        f.list(0x534, addresses); snap = capture_map(f.read)
        p = world_to_pixel(8, 17, snap['context']['dimensions'])
        point = [p[0]+32-120, p[1]+8-210]
        self.assertEqual(len(hit_units(snap, point)), 12)

    def test_list_corruption_count_backlink_cycle_and_unknown_class_fail_closed(self):
        for case in ('count', 'backlink', 'cycle', 'class'):
            with self.subTest(case=case):
                f = Fixture(); node = struct.unpack('<I', f.read(CORE+0x538, 4))[0]
                if case == 'count': f.put(CORE+0x540, 4097)
                if case == 'backlink': f.put(node+4, node)
                if case == 'cycle': f.put(node, node)
                if case == 'class': f.put(UNIT, 0x12345678)
                with self.assertRaises(ValueError): capture_map(f.read)

    def test_membership_changed_between_passes_is_rejected(self):
        f = Fixture(); seen = []
        def mutate(mem, a, n):
            if a == CORE+0x534 and n == 28:
                seen.append(a)
                if len(seen) == 2: mem.put(CORE+0x540, 0)
        f.mutate = mutate
        with self.assertRaisesRegex(ValueError, 'membership changed'): capture_map(f.read)

    def test_stale_pointer_movement_owner_reuse_and_camera_change_are_rejected(self):
        for case in ('moved', 'reused_id', 'owner', 'camera', 'disappeared'):
            with self.subTest(case=case):
                f = Fixture(); snap = capture_map(f.read)
                if case == 'moved': f.write(UNIT+4, struct.pack('<h', 9))
                if case == 'reused_id': f.write(UNIT+10, struct.pack('<H', 43))
                if case == 'owner': f.write(UNIT+8, struct.pack('<H', 2))
                if case == 'camera': f.put(VIEW+0x54, 121)
                if case == 'disappeared': f.list(0x534, [])
                with self.assertRaises(ValueError): inspect_unit(f.read, snap, snap['units'][0])

    def test_bad_roots_or_projection_are_rejected(self):
        for address, value in ((CORE, 0), (VIEW+0x3c, 0), (DOC+0xf2a, 0), (DOC+0xf2e, 3)):
            f = Fixture(); f.put(address, value)
            with self.assertRaises(ValueError): context(f.read)

    def test_native_diamond_hits_center_and_rejects_offmap_without_clamping(self):
        for tw, th in ((16,8), (32,16), (64,32), (128,64)):
            dimensions = [101,202,tw,th]
            for x, y in ((0,0), (1,1), (55,101), (100,201)):
                px, py = world_to_pixel(x,y,dimensions)
                self.assertEqual(native_hit(px+tw//2, py+th//4, dimensions, False), [x,y])
            self.assertIsNone(native_hit(-1,20,dimensions,False))
            self.assertIsNone(native_hit(100000,100000,dimensions,False))

    def test_single_element_toggle_refuses_unknown_and_routes_old_abc_to_existing_tool(self):
        self.assertEqual(mode_for('panel-create'), 'ui')
        self.assertEqual(mode_for('map-trap-fire'), 'hidden-ui')
        self.assertEqual(desired_action('toggle', 'enabled'), 'revert')
        self.assertEqual(desired_action('toggle', 'sealed_or_original'), 'install')
        with self.assertRaises(ValueError): desired_action('toggle', 'unexpected')
        with self.assertRaises(ValueError): mode_for('chat-copy-undelivered')


if __name__ == '__main__': unittest.main()
