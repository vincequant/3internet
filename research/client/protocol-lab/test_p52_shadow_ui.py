"""Execute actual P52 x86 code and selected original SANPK paths in Unicorn.

UI allocation/rendering imports are test doubles. This proves ABI, branches,
bounded updates and recipient selection, not live Wine graphics or RX health.
"""
import hashlib
import ast
import json
import os
from pathlib import Path
import struct
import unittest

from p52_shadow_ui import SITES, FIELDS, SANPK_SHA, plan, display_scale, patch_transaction
from pe_static import PE

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get('SGI_P52_SANPK', str(ROOT/'protocol-archive/evidence/p51-shadow-orphan-20261018/SANPK.readonly.exe')))
BUILD = Path(__file__).resolve().parent/'ui-build'
CODE, CORE, VIEW, OWNER = 0x200000, 0x301000, 0x304000, 0x306000
LORD, STACK, STOP = 0x308000, 0x600000, 0x700000


class Machine:
    def __init__(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import (UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EAX,
            UC_X86_REG_ECX, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
        self.ESP, self.EIP, self.EAX, self.ECX = UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EAX, UC_X86_REG_ECX
        self.saved_regs = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for a, size in ((0, 0x1000), (CODE, 0x2000), (0x300000, 0x40000),
                        (0x400000, 0x200000), (STACK, 0x10000), (STOP, 0x1000)):
            self.uc.mem_map(a, size)
        pe = PE(BINARY)
        self.uc.mem_write(0x400000, pe.data[:0x1000])
        for vs, rva, size, raw in pe.sections:
            self.uc.mem_write(pe.base+rva, pe.data[raw:raw+size])
        self.uc.mem_write(CODE, (BUILD/'shadow_ui.bin').read_bytes())
        self.meta = json.loads((BUILD/'shadow_ui.json').read_text())
        self.calls, self.widgets, self.draws = [], [], []
        self.next_alloc = 0x310000; self.alloc_count = 0; self.fail_alloc = None
        self.card_ids = [1, 6, 12]; self.ratio = 24
        self.hooks = {}
        self.put(CORE, 0x5053c0); self.put(CORE+0x6c0, 1)
        self.put(VIEW+0x7ea, OWNER); self.put(VIEW+0x1c, 0xabcd)
        self.put(OWNER, 0x50a4e0); self.put(LORD, 0x506660)
        self.uc.mem_write(LORD+0x17, bytes([162]))
        for off, value in ((0x1c, 29429), (0x18, 112052), (0x20, 22400), (0x26, 29500), (0x2c, 0)):
            self.put(LORD+off, value)
        self.uc.hook_add(UC_HOOK_CODE, self.hook)

    def get(self, a): return struct.unpack('<I', self.uc.mem_read(a, 4))[0]
    def put(self, a, n): self.uc.mem_write(a, struct.pack('<I', n & 0xffffffff))
    def alloc(self, n):
        a = self.next_alloc; self.next_alloc += (n+15) & ~15
        return a
    def ret(self, value=0, pop=0):
        sp = self.uc.reg_read(self.ESP); target = self.get(sp)
        self.uc.reg_write(self.ESP, sp+4+pop); self.uc.reg_write(self.EAX, value)
        self.uc.reg_write(self.EIP, target)
    def hook(self, uc, address, size, data):
        if address == STOP:
            uc.emu_stop(); return
        if address in self.hooks:
            self.hooks[address](self); return
        sp = uc.reg_read(self.ESP); this = uc.reg_read(self.ECX)
        if address == 0x44b83b:
            self.calls.append('force_id'); self.ret(8)
        elif address == 0x44ff48:
            self.calls.append('find_lord'); self.ret(LORD, 4)
        elif address == 0x46814a:
            self.ret(self.ratio)
        elif address == 0x4d1d22:
            self.alloc_count += 1
            self.ret(0 if self.alloc_count == self.fail_alloc else self.alloc(self.get(sp+4)))
        elif address == 0x4b08b4:
            self.assert_owner(this)
            child = self.get(sp+4); self.widgets.append(child)
            node = self.alloc(12); self.put(node, self.get(OWNER+4)); self.put(node+8, child)
            self.put(OWNER+4, node); self.put(OWNER+0xc, len(self.widgets))
            self.ret(1, 8)
        elif address == 0x484ad8:
            self.put(this, 0x50a468); self.put(this+0x30, 0x133); self.ret(this)
        elif address == 0x467c52:
            out = self.get(sp+4)
            for i, n in enumerate(self.card_ids): self.put(out+4*i, n)
            self.ret(len(self.card_ids), 8)
        elif address == 0x43f5da:
            self.ret(self.get(sp+4)+1000)
        elif address == 0x4cd117:
            n = self.get(sp+4); self.put(this+8, n); self.put(this+4, self.alloc(max(n*4, 4)))
            self.ret(0, 8)
        elif address == 0x4cce7e:
            source = self.get(sp+4); n = self.get(source+8)
            self.calls.append(('card_copy', n))
            self.put(this+8, n); a = self.alloc(max(n*4, 4)); self.put(this+4, a)
            if n: self.uc.mem_write(a, bytes(self.uc.mem_read(self.get(source+4), n*4)))
            self.ret(0, 4)
        elif address == 0x4cce47:
            self.ret()
        elif address == 0x484c98:
            self.draws.append(('cards', this)); self.ret(1)
        elif address == 0x484215:
            self.ret(1)
        elif address == 0x4af73b:
            self.ret(this)
        elif address == 0x4fb754:
            raise AssertionError('IAT is data, not a function')
        elif address == 0x710000:
            self.draws.append(('InvalidateRect', self.get(sp+4))); self.ret(1, 12)

    def assert_owner(self, a):
        if a != OWNER: raise AssertionError('ownership target differs')
    def prepare_api(self):
        self.uc.mem_map(0x710000, 0x1000)
        self.put(0x4fb754, 0x710000)
    def run(self, entry, this, args=(), budget=20000):
        sp = STACK+0x8000
        for r, n in zip(self.saved_regs, (0xaaa, 0xbbb, 0xccc, 0xddd)): self.uc.reg_write(r, n)
        self.uc.reg_write(self.ESP, sp); self.uc.reg_write(self.ECX, this)
        self.put(sp, STOP)
        for i, n in enumerate(args): self.put(sp+4+4*i, n)
        start = CODE+self.meta['entries'][entry] if isinstance(entry, str) else entry
        self.uc.emu_start(start, STOP+1, count=budget)
        if self.uc.reg_read(self.EIP) != STOP: raise AssertionError('payload did not terminate within bound')
        if self.uc.reg_read(self.ESP) != sp+4+4*len(args): raise AssertionError('ABI stack imbalance')
        if tuple(self.uc.reg_read(r) for r in self.saved_regs) != (0xaaa, 0xbbb, 0xccc, 0xddd):
            raise AssertionError('callee-saved register corruption')
        return self.uc.reg_read(self.EAX)


class PanelTests(unittest.TestCase):
    def test_constructor_uses_actual_fields_native_limits_layout_and_ownership(self):
        m = Machine(); core = bytes(m.uc.mem_read(CORE, 0x900)); lord = bytes(m.uc.mem_read(LORD, 0x111))
        m.run('ui_panel_create', OWNER, [CORE])
        self.assertEqual(len(m.widgets), 8)
        values = [162, 24, 29429, 112052, 22400, 29500, 0]
        ys = [0, 0x18, 0x34, 0x4c, 0x68, 0x80, 0x98]
        for widget, field, value, y in zip(m.widgets, FIELDS, values, ys):
            self.assertEqual(m.get(widget), 0x50a3a8)
            self.assertEqual((m.get(widget+0x30), m.get(widget+0x3c), m.get(widget+0x40)),
                             (field['id'], value, field['max']))
            self.assertEqual(m.get(widget+0x2c), y)
        card = m.widgets[-1]
        self.assertEqual(m.get(card+0x2c), 0xb4)
        self.assertEqual([m.get(m.get(card+0x3c)+4*i) for i in range(m.get(card+0x40))], [1001, 1006, 1012])
        self.assertEqual(bytes(m.uc.mem_read(CORE, 0x900)), core)
        self.assertEqual(bytes(m.uc.mem_read(LORD, 0x111)), lord)

    def test_null_invalid_and_nonempty_contexts_do_not_allocate(self):
        for case in ('null_owner', 'wrong_owner', 'nonempty', 'null_core', 'wrong_core', 'minus_slot', 'slot8', 'null_lord', 'wrong_lord', 'slot_changed'):
            with self.subTest(case=case):
                m = Machine(); owner, core = OWNER, CORE
                if case == 'null_owner': owner = 0
                if case == 'wrong_owner': m.put(OWNER, 1)
                if case == 'nonempty': m.put(OWNER+0xc, 1)
                if case == 'null_core': core = 0
                if case == 'wrong_core': m.put(CORE, 1)
                if case == 'minus_slot': m.put(CORE+0x6c0, -1)
                if case == 'slot8': m.put(CORE+0x6c0, 8)
                if case == 'null_lord': m.hooks[0x44ff48] = lambda x: x.ret(0, 4)
                if case == 'wrong_lord': m.put(LORD, 1)
                if case == 'slot_changed':
                    def change(x): x.put(CORE+0x6c0, 0); x.ret(LORD, 4)
                    m.hooks[0x44ff48] = change
                m.run('ui_panel_create', owner, [core]); self.assertEqual(m.alloc_count, 0)

    def test_allocator_failure_never_passes_null_to_constructor_or_owner(self):
        for nth in range(1, 9):
            with self.subTest(nth=nth):
                m = Machine(); m.fail_alloc = nth
                m.run('ui_panel_create', OWNER, [CORE]); self.assertEqual(len(m.widgets), 7)
                self.assertNotIn(0, m.widgets)

    def test_constructor_does_not_duplicate_children(self):
        m = Machine(); m.run('ui_panel_create', OWNER, [CORE]); count = m.alloc_count
        m.run('ui_panel_create', OWNER, [CORE]); self.assertEqual(m.alloc_count, count)

    def test_seven_refreshers_write_only_their_control_and_request_repaint(self):
        for i, field in enumerate(FIELDS):
            with self.subTest(field=field['name']):
                m = Machine(); m.prepare_api(); m.run('ui_panel_create', OWNER, [CORE])
                before = [m.get(a+0x3c) for a in m.widgets[:7]]
                m.run('ui_stat_%x' % field['id'], VIEW, [123+i])
                expected = before[:]; expected[i] = 123+i
                self.assertEqual([m.get(a+0x3c) for a in m.widgets[:7]], expected)
                self.assertEqual(m.draws[-1], ('InvalidateRect', 0xabcd))

    def test_missing_widgets_container_fallback_and_cyclic_list_are_bounded_noops(self):
        for case in ('null_view', 'null_container', 'wrong_container', 'missing', 'fallback', 'cycle', 'wrong_type'):
            with self.subTest(case=case):
                m = Machine(); view = VIEW; widget = 0x307000; node = 0x307100
                m.put(node+8, widget); m.put(OWNER+4, node)
                m.put(widget, 0x50a3a8); m.put(widget+0x30, 0x12e)
                if case == 'null_view': view = 0
                if case == 'null_container': m.put(VIEW+0x7ea, 0)
                if case == 'wrong_container': m.put(OWNER, 1)
                if case == 'missing': m.put(OWNER+4, 0)
                if case == 'fallback': m.put(node+8, OWNER)
                if case == 'cycle': m.put(node, node)
                if case == 'wrong_type': m.put(widget, 0x50a468)
                m.run('ui_stat_12c', view, [987], budget=2000)
                self.assertEqual(m.get(widget+0x3c), 0)

    def test_null_hwnd_never_invalidates_all_windows(self):
        m = Machine(); m.run('ui_panel_create', OWNER, [CORE]); m.put(VIEW+0x1c, 0)
        m.run('ui_stat_12c', VIEW, [167]); self.assertEqual(m.get(m.widgets[0]+0x3c), 167)
        self.assertFalse(any(x[0] == 'InvalidateRect' for x in m.draws))

    def test_cards_reject_null_fallback_oversized_and_missing_source(self):
        for case in ('null', 'fallback', 'source_null', 'oversized', 'negative_size', 'missing_source'):
            with self.subTest(case=case):
                m = Machine(); card, source = 0x307000, 0x307200
                m.put(card, 0x50a468)
                if case == 'null': card = 0
                if case == 'fallback': card = OWNER
                if case == 'source_null': source = 0
                if case == 'oversized': m.put(source+8, 6)
                if case == 'negative_size': m.put(source+8, -1)
                if case == 'missing_source': m.put(source+8, 2)
                m.run('ui_cards_update', card, [source])
                self.assertFalse(m.draws); self.assertFalse(m.calls)

    def test_empty_cards_use_native_copy_and_do_not_keep_source_alias(self):
        m = Machine(); card, source = 0x307000, 0x307200; m.put(card, 0x50a468)
        m.run('ui_cards_update', card, [source])
        self.assertIn(('card_copy', 0), m.calls)
        self.assertEqual(m.draws, [('cards', card)])

    def test_original_bar_scale_matches_port_at_boundaries(self):
        from unicorn.x86_const import UC_X86_REG_EAX
        for maximum in (100, 200, 2000000, 10000000):
            for current in (0, 100, 200, 29999, 30000, 30001, 50000, 50001, 100000, 100001, maximum):
                with self.subTest(maximum=maximum, current=current):
                    m = Machine(); m.put(OWNER+0x3c, current); m.put(OWNER+0x40, maximum)
                    m.run(0x484385, OWNER, [0x307000, 0x307004, 0x307008])
                    self.assertEqual((m.get(0x307004), m.get(0x307000)), display_scale(current, maximum))
                    self.assertEqual(m.get(0x307008), current)


class PatchTests(unittest.TestCase):
    def test_existing_nullguards_and_caves_survive_all_optional_detours(self):
        pe = PE(BINARY); image = bytearray(pe.data)
        tree = ast.parse(Path(__file__).with_name('p51_shadow_inject.py').read_text())
        guards = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'NULLGUARD_PATCHES' for t in n.targets))
        meta = json.loads((BUILD/'shadow_ui.json').read_text())
        for rva, orig, patch, label in guards:
            a = pe.offset(0x400000+rva); raw = bytes.fromhex(patch); image[a:a+len(raw)] = raw
        for element in SITES:
            row = plan(CODE, meta['entries'], element); a = pe.offset(row['site'])
            self.assertEqual(image[a:a+5], bytes.fromhex(row['before']))
            image[a:a+5] = bytes.fromhex(row['after'])
        changed_entries = {s[0] for s in SITES.values()}
        for rva, orig, patch, label in guards:
            if 0x400000+rva in changed_entries:
                continue
            a = pe.offset(0x400000+rva); self.assertEqual(image[a:a+len(bytes.fromhex(patch))], bytes.fromhex(patch), label)

    def test_identity_and_every_expected_site_match_actual_original_or_seal(self):
        pe = PE(BINARY); self.assertEqual(hashlib.sha256(pe.data).hexdigest(), SANPK_SHA)
        meta = json.loads((BUILD/'shadow_ui.json').read_text())
        for name, (site, before, entry, op) in SITES.items():
            with self.subTest(name=name):
                if not name.startswith(('stat-', 'cards-', 'panel-')):
                    self.assertEqual(pe.read(site, len(before)), before)
                row = plan(CODE, meta['entries'], name)
                raw = bytes.fromhex(row['after'])
                self.assertEqual(raw[0], op)
                self.assertEqual(site+5+struct.unpack_from('<i', raw, 1)[0], CODE+meta['entries'][entry])

    def test_transaction_refuses_unexpected_bytes_before_first_write(self):
        calls = []
        with self.assertRaises(ValueError):
            patch_transaction([(1, b'A', b'B')], lambda a, n: b'X', lambda a, b: calls.append((a, b)))
        self.assertEqual(calls, [])

    def test_partial_failed_write_is_also_rolled_back(self):
        memory = {1: b'AA', 4: b'CC'}; calls = []
        def put(a, raw):
            calls.append((a, raw)); memory[a] = raw
            if a == 4 and raw == b'DD': memory[a] = b'DC'; raise OSError('partial write')
        with self.assertRaises(OSError):
            patch_transaction([(1, b'AA', b'BB'), (4, b'CC', b'DD')], lambda a, n: memory[a], put)
        self.assertEqual(memory, {1: b'AA', 4: b'CC'})

    def test_renderer_helpers_preserve_stack_registers_and_null_semantics(self):
        for entry, args in (('ui_visible_xy', [999, 123]), ('ui_visible_test', [])):
            for this in (0, LORD):
                m = Machine(); original = bytes(m.uc.mem_read(CORE, 0x900))
                self.assertEqual(m.run(entry, this, args), bool(this))
                self.assertEqual(bytes(m.uc.mem_read(CORE, 0x900)), original)

    def test_actual_fog_render_branch_is_unmasked_without_changing_vision_bytes(self):
        from unicorn.x86_const import UC_X86_REG_EBP
        for patched, destination in ((False, 0x433128), (True, 0x43310f)):
            with self.subTest(patched=patched):
                m = Machine(); ebp = STACK+0x9000; m.uc.reg_write(UC_X86_REG_EBP, ebp)
                m.uc.reg_write(m.ESP, STACK+0x8000)
                m.put(ebp-0x38, LORD); m.put(ebp-0x14, 12); m.put(ebp-0x1c, 19)
                if patched:
                    row = plan(CODE, m.meta['entries'], 'map-tiles')
                    m.uc.mem_write(row['site'], bytes.fromhex(row['after']))
                for a in (0x43310f, 0x433128): m.hooks[a] = lambda x: x.uc.emu_stop()
                original = bytes(m.uc.mem_read(LORD, 0x111))
                m.uc.emu_start(0x4330d1, STOP+1, count=200)
                self.assertEqual(m.uc.reg_read(m.EIP), destination)
                self.assertEqual(bytes(m.uc.mem_read(LORD, 0x111)), original)


class ChatTests(unittest.TestCase):
    def test_original_recipient_builder_requires_relation3_in_both_directions(self):
        m = Machine(); m.put(VIEW+0x3c, CORE-0x912); m.put(0x53bb30, CORE)
        lords = {8: LORD, 1: LORD+0x200, 5: LORD+0x400, 6: LORD+0x600}
        for i in range(8): m.put(CORE+0x46+i*0x87, 2)
        for i, force in enumerate((8, 1, 5, 6)):
            m.put(CORE+0x46+i*0x87, 0); m.put(CORE+0x4a+i*0x87, force)
            m.put(CORE+0xa+i*0x87, 1000+force)
        for force, addr in lords.items():
            m.put(addr, 0x506660); m.uc.mem_write(addr+8, struct.pack('<H', force))
            ptr = m.alloc(20); m.uc.mem_write(ptr, ('force%d' % force).encode()+b'\0'); m.put(addr+0xa, ptr)
        for force, reverse in ((1, 3), (5, 2), (6, 1)):
            m.uc.mem_write(LORD+0x32+force, bytes([3 if force != 6 else 1]))
            m.uc.mem_write(lords[force]+0x32+8, bytes([reverse]))
        def find(x): x.ret(lords.get(x.get(x.uc.reg_read(x.ESP)+4), 0), 4)
        m.hooks[0x44ff48] = find
        m.hooks[0x44a6dd] = lambda x: x.ret()
        m.hooks[0x44a6f0] = lambda x: x.ret()
        m.hooks[0x4d1d6f] = lambda x: x.ret(x.uc.reg_read(x.ECX))
        m.hooks[0x4d2002] = lambda x: x.ret(x.uc.reg_read(x.ECX), 4)
        recipients = []
        def append(x):
            ptr = x.get(x.uc.reg_read(x.ESP)+4); recipients.append(x.get(ptr)); x.ret(1, 4)
        m.hooks[0x4cc436] = append
        m.run(0x499505, VIEW, [0x307800])
        self.assertEqual(recipients, [1001])

    def receiver(self, sender=111, target=0, row_state=0):
        m = Machine(); m.uc.mem_map(0x720000, 0x1000)
        packet = 0x307800; text = '盟军消息'.encode('gbk'); name = '丁满'.encode('gbk')
        m.put(VIEW+0x3c, CORE-0x912)
        m.put(CORE+0xa, 111); m.put(CORE+0x46, row_state)
        m.uc.mem_write(CORE+0x4e, struct.pack('<H', 8))
        def string(raw):
            a = m.alloc(len(raw)+13); m.put(a, 1); m.put(a+4, len(raw)); m.put(a+8, len(raw))
            m.uc.mem_write(a+12, raw+b'\0'); return a+12
        nameptr = string(name); m.put(CORE+0x12, nameptr)
        m.put(packet, sender); m.put(packet+4, target); m.put(packet+8, len(text)+1)
        m.uc.mem_write(packet+12, text+b'\0')
        def cstr(a):
            b = bytes(m.uc.mem_read(a, 128)); return b.split(b'\0')[0]
        def ctor(x):
            sp = x.uc.reg_read(x.ESP); this = x.uc.reg_read(x.ECX)
            x.put(this, string(cstr(x.get(sp+4)))); x.ret(this, 4)
        def append(x):
            sp = x.uc.reg_read(x.ESP); this = x.uc.reg_read(x.ECX)
            x.put(this, string(cstr(x.get(this))+cstr(x.get(sp+4)))); x.ret(this, 4)
        display, freed = [], []
        def show(x):
            sp = x.uc.reg_read(x.ESP)
            display.append({'name': cstr(x.get(sp+4)), 'text': cstr(x.get(sp+8)),
                            'private': x.get(sp+12), 'color': x.get(sp+16), 'style': x.get(sp+20)})
            x.ret(1, 20)
        def free(x):
            freed.append(x.get(x.uc.reg_read(x.ESP)+4)); x.ret(1, 4)
        m.hooks[0x472e28] = lambda x: x.ret(string(b''))
        m.hooks[0x4d1f28] = ctor; m.hooks[0x4d21e2] = append
        m.hooks[0x4d1eba] = lambda x: x.ret()
        m.hooks[0x42c066] = show; m.hooks[0x720000] = free
        m.put(0x4fb49c, 0x720000)
        m.run(0x4993e2, VIEW, [0, packet])
        return display, freed, packet, name, text

    def test_original_receiver_displays_public_sender_and_text_and_frees_once(self):
        display, freed, packet, name, text = self.receiver()
        self.assertEqual([(r['name'], r['text'], r['private']) for r in display], [(name, text, 0)])
        self.assertEqual(freed, [packet])

    def test_original_receiver_already_distinguishes_received_private_chat(self):
        display, freed, packet, name, text = self.receiver(target=222)
        self.assertEqual([(r['name'], r['text'], r['private']) for r in display], [(name, text, 1)])
        self.assertEqual(freed, [packet])

    def test_unknown_or_inactive_sender_is_discarded_and_packet_freed(self):
        for sender, state in ((999, 0), (111, 2)):
            with self.subTest(sender=sender, state=state):
                display, freed, packet, _, _ = self.receiver(sender=sender, row_state=state)
                self.assertEqual(display, []); self.assertEqual(freed, [packet])

    def test_original_private_send_loop_uses_selected_member_ids_not_my_slot(self):
        m = Machine()
        from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI
        # Enter the original loop after UI edit-text/checkbox acquisition.
        # This test stops before CString cleanup; network APIs are captured.
        ebp = STACK+0x9000; m.uc.reg_write(UC_X86_REG_EBP, ebp)
        m.uc.reg_write(m.ESP, STACK+0x8000)
        m.uc.reg_write(UC_X86_REG_EBX, OWNER); m.uc.reg_write(UC_X86_REG_EDI, VIEW)
        m.put(ebp-0x10, 0x307800); m.put(ebp-0x18, 0x307700)
        for i, (member, selected) in enumerate(((111, 1), (222, 0), (333, 1))):
            node, row = 0x307000+i*0x40, 0x307020+i*0x40
            m.put(node, node+0x40 if i < 2 else 0); m.put(node+8, row)
            m.put(row, member); m.put(row+8, selected)
        m.put(OWNER+4, 0x307000); sent = []
        def send(x):
            sp = x.uc.reg_read(x.ESP); sent.append(x.get(sp+4)); x.ret(1, 8)
        m.hooks[0x42acea] = send
        m.hooks[0x42b998] = lambda x: x.uc.emu_stop()
        m.uc.emu_start(0x42b964, STOP+1, count=1000)
        self.assertEqual(m.uc.reg_read(m.EIP), 0x42b998)
        self.assertEqual(sent, [111, 333])


if __name__ == '__main__':
    unittest.main()
