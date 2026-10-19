"""Original draw/hit branches and the immutable P53 payload in Unicorn."""
import hashlib
import json
from pathlib import Path
import struct
import unittest

from p52_shadow_ui import detour
from p53_hidden_draw_build import GROUPS, SITE, ORIGINAL
from p53_unit_data import native_hit, world_to_pixel
from test_p52_shadow_ui import Machine, CORE, LORD, OWNER, VIEW, STACK, STOP

CODE, ENTITY, BUILD = 0x220000, 0x309000, Path(__file__).resolve().parent/'hidden-build'
ALL = (1 << len(GROUPS))-1


def machine(mask):
    m = Machine(); m.uc.mem_map(CODE, 0x2000)
    raw = (BUILD/'hidden_draw.bin').read_bytes(); meta = json.loads((BUILD/'hidden_draw.json').read_text())
    if len(raw) != meta['size'] or hashlib.sha256(raw).hexdigest() != meta['sha256']:
        raise AssertionError('payload/build mismatch')
    m.uc.mem_write(CODE, raw)
    if mask:
        m.uc.mem_write(SITE, detour(SITE, CODE+meta['entries']['hidden_%d' % mask], 0xe8))
    m.put(OWNER, 0x504f68); m.put(OWNER+0x1c, ENTITY); m.put(OWNER+0x20, 0)
    m.put(0x53bb30, CORE)
    m.uc.mem_write(ENTITY, struct.pack('<IhhHH', 0x508878, 8, 17, 1, 42))
    m.uc.mem_write(ENTITY+0xd, b'\x01')
    return m


def branch(m, start=0x4afc55, yes=0x4afc63, no=0x4afcde):
    from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESI
    ebp = STACK+0x9000; m.uc.reg_write(UC_X86_REG_EBP, ebp)
    m.uc.reg_write(m.ESP, STACK+0x8000); m.put(ebp-4, OWNER)
    m.uc.reg_write(UC_X86_REG_ESI, OWNER)
    # Enter actual drawing code, stop only AFTER its original conditional jump.
    for a in (yes, no): m.hooks[a] = lambda x: x.uc.emu_stop()
    m.uc.emu_start(start, STOP+1, count=1000)
    result = m.uc.reg_read(m.EIP)
    if result not in (yes,no): raise AssertionError('draw branch did not terminate')
    return result == yes


class HiddenTests(unittest.TestCase):
    def test_real_bitmap_paint_and_native_entity_predicates_before_after_each_group(self):
        for name, (bit, vtables) in GROUPS.items():
            for vt in vtables:
                with self.subTest(group=name, vtable=hex(vt)):
                    outcomes = []
                    for mask in (0, bit):
                        for wrapper in (0x504f68,0x504fd8,0x505048):
                            m = machine(mask); m.put(ENTITY, vt);m.put(OWNER,wrapper)
                            world = bytes(m.uc.mem_read(CORE, 0x900)); entity = bytes(m.uc.mem_read(ENTITY, 168))
                            lord = bytes(m.uc.mem_read(LORD, 0x111))
                            outcomes.append(branch(m))
                            self.assertEqual(bytes(m.uc.mem_read(CORE, 0x900)), world)
                            self.assertEqual(bytes(m.uc.mem_read(ENTITY, 168)), entity)
                            self.assertEqual(bytes(m.uc.mem_read(LORD, 0x111)), lord)
                    self.assertEqual(outcomes, [False]*3+[True]*3)

    def test_independent_bits_do_not_enable_other_groups(self):
        for name, (bit, vtables) in GROUPS.items():
            for other, (other_bit, other_vtables) in GROUPS.items():
                if name == other: continue
                m = machine(other_bit); m.put(ENTITY, vtables[0])
                self.assertFalse(branch(m), (name, other))
            m = machine(ALL & ~bit); m.put(ENTITY, vtables[0]); self.assertFalse(branch(m), name)

    def test_native_image_disabled_flags_are_not_bypassed(self):
        for flags in (0x80000000,0x20000000,0xa0000000):
            m = machine(ALL); m.put(OWNER+0x20,flags)
            self.assertFalse(branch(m))

    def test_unrelated_widgets_call_original_method_and_preserve_abi(self):
        m = machine(ALL)
        from unicorn.x86_const import UC_X86_REG_EDX
        # An unrelated widget with its real native 4b0012 method.
        m.put(OWNER, 0x50a3a8); m.uc.reg_write(UC_X86_REG_EDX,0xabcdef)
        self.assertTrue(branch(m))
        self.assertEqual(m.uc.reg_read(UC_X86_REG_EDX),0xabcdef)

    def test_native_hit_test_remains_hidden_and_shared_rule_predicates_untouched(self):
        for mask in (0,ALL):
            m = machine(mask)
            self.assertFalse(branch(m,0x4afd45,0x4afd50,0x4afd92))
            from pe_static import PE
            from test_p52_shadow_ui import BINARY
            pe = PE(BINARY)
            for start,end in ((0x468662,0x468768),(0x476bfc,0x476d19),(0x483859,0x4838a8),
                              (0x4afd2f,0x4afd9b)):
                self.assertEqual(bytes(m.uc.mem_read(start,end-start)),pe.read(start,end-start))

    def test_revert_restores_original_branch_with_identical_world(self):
        m = machine(ALL); self.assertTrue(branch(m))
        m.uc.mem_write(SITE, ORIGINAL); m.uc.ctl_remove_cache(SITE,SITE+5)
        self.assertFalse(branch(m))

    def test_exact_diamond_hit_port_against_original_x86_for_zoom_edges_and_scroll_coordinates(self):
        m = Machine(); m.put(VIEW+0x3c,CORE-0x912); out=0x307800
        for tw,th in ((16,8),(32,16),(64,32),(128,64)):
            dimensions=[101,202,tw,th]
            m.uc.mem_write(CORE-0x912+0xf22,struct.pack('<4i',*dimensions))
            points=[(0,0),(1,1),(tw//2-1,th//2-1),(tw//2,th//2),(tw-1,th-1),(6553,3221)]
            for x,y in ((0,0),(1,1),(5,9),(100,201)):
                m.run(0x4986dd,VIEW,[out,x,y])
                self.assertEqual(list(struct.unpack('<2i',m.uc.mem_read(out,8))),world_to_pixel(x,y,dimensions))
                px,py=world_to_pixel(x,y,dimensions)
                points += [(px+dx,py+dy) for dx in (0,1,tw//2,tw-1) for dy in (0,1,th//4,th//2-1)]
            for px,py in points:
                with self.subTest(tile=[tw,th],pixel=[px,py]):
                    m.run(0x498591,VIEW,[out,px,py])
                    native=list(struct.unpack('<2i',m.uc.mem_read(out,8)))
                    self.assertEqual(native_hit(px,py,dimensions),native)


if __name__ == '__main__': unittest.main()
