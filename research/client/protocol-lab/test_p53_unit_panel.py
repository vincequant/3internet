"""D-only evidence: original x86 hit math, actual hook and coherent reads.

Unicorn runs on the analysis host; UI smoke separately uses synthetic Win32
controls. Neither is a live game/window/RX stability acceptance test.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
import unittest

from p53_unit_model import (UNIT_TYPES, UNIT_SIZE, FIELD_NAMES, native_tile, screen_to_tile,
    decode_unit, inspect_click, preview, parse_preview, panel_text, enrich_rows)
from p53_unit_panel import SITE, BEFORE, MAGIC, MAILBOX_SIZE, make_mailbox, click_from_mailbox, tick_age
from p52_shadow_ui import patch_transaction, SANPK_SHA
from pe_static import PE

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get('SGI_P53_SANPK', str(ROOT/'protocol-archive/evidence/p51-shadow-orphan-20261018/SANPK.readonly.exe')))
FIXTURES = Path(os.environ.get('SGI_P53_FIXTURES', str(ROOT/'evidence/map-accuracy-320-20261011')))
BRIDGE = Path(os.environ.get('SGI_P53_BRIDGE', str(ROOT/'client/SGI-Hub-CrossOver-M4-0.2/bridge')))
BUILD = Path(__file__).resolve().parent/'unit-panel-build'
CODE, MAILBOX, VIEW, CORE = 0x200000, 0x201000, 0x304000, 0x301000
DOC, STACK, STOP = CORE-0x912, 0x600000, 0x700000


def unit_raw(vt=0x508878, xy=(10,20), owner=4, uid=17):
    raw = bytearray(UNIT_SIZE)
    struct.pack_into('<IhhHH', raw, 0, vt, *xy, owner, uid)
    struct.pack_into('<3H', raw, 0xf, 12, 65535, 65535)
    for offset, value in ((0x15,21000), (0x19,15000)):
        struct.pack_into('<I', raw, offset, value)
    raw[0x1d], raw[0x29], raw[0x20] = 40, 36, 10
    return bytes(raw)


class Memory:
    def __init__(self, units=None):
        self.heap = bytearray(0x80000); self.globals = bytearray(0x1000)
        self.put(CORE, 0x5053c0); self.put(DOC,0x504d40); self.put(VIEW,0x50b730)
        self.put(VIEW+0x3c,DOC); self.put(VIEW+0x1c,0x1234)
        self.put(0x53bb30,CORE); self.put(0x53b930,VIEW)
        self.write(DOC+0xf22, struct.pack('<4i',101,202,64,32))
        self.objects = []
        for i, raw in enumerate([unit_raw()] if units is None else units):
            obj = 0x320000+i*0x100; self.write(obj,raw); self.objects.append(obj)
        self.make_list(0x534,self.objects,0x330000)
        self.make_list(0x514,[],0x340000)
        self.click = dict(view=VIEW,document=DOC,core=CORE,hwnd=0x1234,
            point=[672,328],origin=[0,0],dimensions=[101,202,64,32],
            clock_hex=self.read(CORE+0x4d0,12).hex(),client_size=[1800,1000])

    def region(self, a, n):
        if 0x300000 <= a and a+n <= 0x380000: return self.heap,a-0x300000
        if 0x53b000 <= a and a+n <= 0x53c000: return self.globals,a-0x53b000
        raise ValueError('outside synthetic memory: '+hex(a))
    def read(self, a, n):
        data,offset=self.region(a,n);return bytes(data[offset:offset+n])
    def write(self, a, raw):
        data,offset=self.region(a,len(raw));data[offset:offset+len(raw)]=raw
    def put(self,a,value):self.write(a,struct.pack('<I',value))
    def make_list(self,offset,objects,nodes):
        self.write(CORE+offset,bytes(28))
        self.write(CORE+offset+4,struct.pack('<III',nodes if objects else 0,
            nodes+(len(objects)-1)*16 if objects else 0,len(objects)))
        for i,obj in enumerate(objects):
            self.write(nodes+i*16,struct.pack('<III', nodes+(i+1)*16 if i+1<len(objects) else 0,
                nodes+(i-1)*16 if i else 0,obj))


class DataTests(unittest.TestCase):
    def test_wrong_prefix_rejects_before_process_discovery(self):
        from unittest.mock import patch
        from p53_unit_inject import main
        with patch.dict(os.environ,{'WINEPREFIX':'/unrelated/prefix-sikarugir10'}), \
                patch.object(sys,'argv',['p53_unit_inject.py','--state','unused.json']), \
                patch('p51_shadow_inject.find_process',side_effect=AssertionError('must not enumerate')):
            with self.assertRaisesRegex(SystemExit,'before process discovery'):main()

    def test_vtables_equal_existing_bridge_without_importing_its_GUI(self):
        tree=ast.parse((BRIDGE/'state_extensions.py').read_text())
        value=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                   and any(isinstance(t,ast.Name) and t.id=='UNIT_TYPES' for t in n.targets))
        self.assertEqual(UNIT_TYPES,value)

    def test_all_twelve_classes_all_owners_and_colocated_units(self):
        memory=Memory([unit_raw(vt,owner=i,uid=i) for i,vt in enumerate(UNIT_TYPES)])
        o=inspect_click(memory.read,memory.click)
        self.assertEqual(len(o['units']),12)
        self.assertEqual([u['owner_raw'] for u in o['units']],list(range(12)))

    def test_empty_tile_does_not_select_neighbor(self):
        memory=Memory([unit_raw(xy=(11,20))]);o=inspect_click(memory.read,memory.click)
        self.assertEqual(o['units'],[])
        self.assertIn('未代选邻格',panel_text(o))

    def test_fields_and_out_of_domain_are_not_clamped_into_facts(self):
        raw=bytearray(unit_raw());raw[0x1d]=101;raw[0x29]=201
        struct.pack_into('<I',raw,0x15,100001)
        row=decode_unit(0x320000,bytes(raw))
        for key in ('soldiers','morale','training'):self.assertIsNone(row['values'][key])
        self.assertEqual(row['raw_values']['training'],201)
        self.assertEqual(row['values']['move_remaining'],10)

    def test_transport_morale_fifty_and_wanderer_one_hundred(self):
        for vt,expected in ((0x5099d0,None),(0x50bdb8,51)):
            raw=bytearray(unit_raw(vt));raw[0x1d]=51
            self.assertEqual(decode_unit(0x320000,bytes(raw))['values']['morale'],expected)

    def test_corrupt_membership_backlink_and_limit_fail_closed(self):
        for address,value in ((0x330000,0x330000),(0x330004,1),(CORE+0x540,4097)):
            m=Memory();m.put(address,value)
            with self.assertRaises(ValueError):inspect_click(m.read,m.click)

    def test_changed_record_is_not_displayed(self):
        m=Memory();counts={}
        def changing(a,n):
            key=(a,n);counts[key]=counts.get(key,0)+1
            raw=m.read(a,n)
            if a==m.objects[0] and n==UNIT_SIZE and counts[key]>1:
                return raw[:0x15]+struct.pack('<I',999)+raw[0x19:]
            return raw
        with self.assertRaisesRegex(ValueError,'world changed'):inspect_click(changing,m.click)

    def test_changed_clock_or_source_root_rejects(self):
        for address in (CORE+0x4d0,0x53b930,VIEW+0x3c):
            m=Memory();m.put(address,123)
            with self.assertRaises(ValueError):inspect_click(m.read,m.click)

    def test_unknown_class_and_short_record_are_not_guessed(self):
        with self.assertRaises(ValueError):decode_unit(0x320000,unit_raw()[:40])
        m=Memory();m.put(m.objects[0],0x123456)
        with self.assertRaisesRegex(ValueError,'unknown unit'):inspect_click(m.read,m.click)

    def test_preview_is_copy_only_and_rejects_unknown_fields(self):
        m=Memory();before=bytes(m.heap);o=inspect_click(m.read,m.click)
        changed=preview(o,dict(soldiers=12345,morale=95,training=99))
        self.assertEqual(o['units'][0]['values']['soldiers'],21000)
        self.assertEqual(changed['units'][0]['values']['soldiers'],12345)
        self.assertEqual(bytes(m.heap),before)
        self.assertIn('本地预览',panel_text(changed,FIELD_NAMES))
        for edits in ({'defence':100},{'training':101},{'morale':-1}):
            with self.assertRaises(ValueError):preview(o,edits)
        self.assertEqual(parse_preview('soldiers=12000,morale=60'),dict(soldiers=12000,morale=60))

    def test_preview_never_chooses_one_of_multiple_units(self):
        m=Memory([unit_raw(uid=1),unit_raw(uid=2)]);o=inspect_click(m.read,m.click)
        with self.assertRaises(ValueError):preview(o,dict(soldiers=1))

    def test_display_elements_start_at_identity_and_unknowns_stay_unknown(self):
        m=Memory();o=inspect_click(m.read,m.click)
        self.assertNotIn('兵力：',panel_text(o))
        text=panel_text(o,FIELD_NAMES)
        self.assertIn('兵力：21000',text);self.assertIn('防御/完整伤害：未定位',text)
        self.assertIn('未知',text);self.assertNotIn('21000',panel_text({'error':'过期'}))

    def test_historical_units_align_with_existing_ground_truth(self):
        raw=json.loads((FIXTURES/'live-native-raw-tiles.json').read_text())
        rows={r['unit_id']:decode_unit(int(r['address'],16),bytes.fromhex(r['raw_hex'])) for r in raw['units']}
        for uid,soldiers,morale,training in ((27,21000,85,36),(28,3500,75,56),(32,3500,75,39)):
            self.assertEqual([rows[uid]['values'][key] for key in ('soldiers','morale','training')],
                             [soldiers,morale,training])
        self.assertEqual(len(rows),40)

    def test_existing_pure_combat_rules_on_historical_raw_records(self):
        sys.path.insert(0,str(BRIDGE))
        from unit_combat import enrich_unit_combat
        raw=json.loads((FIXTURES/'live-native-raw-tiles.json').read_text())
        units=[decode_unit(int(r['address'],16),bytes.fromhex(r['raw_hex'])) for r in raw['units']]
        generals=[]
        for g in raw['generals']:
            b=bytes.fromhex(g['raw_hex'])
            generals.append(dict(general_id_raw=g['general_id'],owner_raw=g['owner'],raw_hex=b.hex(),
                status_code=struct.unpack_from('<H',b,0x21)[0],
                attributes=dict(zip(('lead','war','intel','pol','cha'),b[0x25:0x2a])),
                combat_modifier_flags_word=struct.unpack_from('<H',b,0x44)[0]))
        for u in units:u['on_water']=False
        enrich_rows(units,generals,enrich_unit_combat)
        byid={u['unit_id']:u for u in units}
        for uid,ability,index in ((27,89,867),(28,77,372),(32,74,184)):
            self.assertEqual(byid[uid]['basic_combat_power'],ability)
            self.assertEqual(byid[uid]['native_attack_index'],index)

    def test_screen_bounds_and_corrupt_projection_reject(self):
        for point in ((-1,1),(1800,4),(1,1000)):
            with self.assertRaises(ValueError):screen_to_tile(point,(0,0),(101,202,64,32),(1800,1000))
        with self.assertRaises(ValueError):native_tile((40,30),(101,202,63,32))


class X86:
    def __init__(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        from unicorn import x86_const as r
        self.r=r;self.uc=Uc(UC_ARCH_X86,UC_MODE_32)
        for a,n in ((CODE,0x2000),(0x300000,0x80000),(0x400000,0x200000),(STACK,0x10000),(STOP,0x2000)):
            self.uc.mem_map(a,n)
        p=PE(BINARY);self.uc.mem_write(0x400000,p.data[:0x1000])
        for vs,rva,size,offset in p.sections:self.uc.mem_write(p.base+rva,p.data[offset:offset+size])
        self.uc.mem_write(CODE,(BUILD/'unit_click.bin').read_bytes())
        self.uc.mem_write(MAILBOX,make_mailbox())
        self.put(0x4fb2f8,STOP+0x1000)
        m=Memory();self.uc.mem_write(0x300000,bytes(m.heap));self.uc.mem_write(0x53b000,bytes(m.globals))
        self.now=1000;self.stopped=None;self.writes=[];self.calls=[]
        self.uc.hook_add(UC_HOOK_CODE,self.hook)
        self.uc.hook_add(UC_HOOK_MEM_WRITE,lambda uc,access,a,n,value,data:self.writes.append((a,n)))
    def put(self,a,value):self.uc.mem_write(a,struct.pack('<I',value&0xffffffff))
    def get(self,a):return struct.unpack('<I',self.uc.mem_read(a,4))[0]
    def hook(self,uc,a,n,data):
        r=self.r
        if a in (STOP,0x4988e9):self.stopped=a;uc.emu_stop()
        if a==STOP+0x1000:
            self.calls.append('GetTickCount');sp=uc.reg_read(r.UC_X86_REG_ESP)
            uc.reg_write(r.UC_X86_REG_EAX,self.now);uc.reg_write(r.UC_X86_REG_EIP,self.get(sp))
            uc.reg_write(r.UC_X86_REG_ESP,sp+4)
    def click(self,enabled=True,deadline=2000):
        r=self.r;frame=STACK+0x8000
        self.put(frame-12,0x111);self.put(frame-8,0x222);self.put(frame-4,0x333)
        self.put(frame,0x444);self.put(frame+4,STOP)
        self.put(MAILBOX+4,int(enabled));self.put(MAILBOX+8,deadline)
        initial={r.UC_X86_REG_ESP:frame-12,r.UC_X86_REG_EBP:frame,r.UC_X86_REG_ESI:VIEW,
                 r.UC_X86_REG_EDI:672,r.UC_X86_REG_EBX:328,r.UC_X86_REG_ECX:0,
                 r.UC_X86_REG_EDX:0xabc,r.UC_X86_REG_EAX:0xdef,r.UC_X86_REG_EFLAGS:0x202}
        for reg,value in initial.items():self.uc.reg_write(reg,value)
        self.writes.clear();self.uc.emu_start(CODE,STOP+0x2000,count=500)
        return initial


class MachineTests(unittest.TestCase):
    def test_native_ui_hit_filter_excludes_unit_visuals_so_click_reaches_hook(self):
        p=PE(BINARY)
        self.assertEqual(p.read(0x419678,5),b'\x68'+struct.pack('<I',0x50cf50))
        self.assertIn(b'CVisualButtonObject',p.read(p.u32(0x50cf50),64))
        for visual in (0x504f20,0x504f38):
            seen=set();current=visual
            while current:
                self.assertNotIn(current,seen);seen.add(current)
                current=p.u32(current+0x10)
            self.assertNotIn(0x50cf50,seen)

    def test_morale_ranges_are_anchored_to_all_twelve_native_vtables(self):
        p=PE(BINARY)
        for vt in UNIT_TYPES:
            function=p.u32(vt+0x9c)
            maximum=50 if vt==0x5099d0 else 100
            self.assertEqual(p.read(function,4),bytes((0x6a,maximum,0x58,0xc3)))

    def test_click_mailbox_to_coherent_fields_to_panel_text(self):
        m=X86();m.click()
        click=click_from_mailbox(bytes(m.uc.mem_read(MAILBOX,MAILBOX_SIZE)))
        click['client_size']=[1800,1000]
        o=inspect_click(lambda a,n:bytes(m.uc.mem_read(a,n)),click)
        self.assertEqual(o['tile'],[10,20]);self.assertEqual(o['units'][0]['unit_id'],17)
        self.assertIn('兵力：21000',panel_text(o,FIELD_NAMES))

    def test_site_preserves_existing_p51_and_optional_ui_ranges(self):
        from p52_shadow_ui import SITES
        tree=ast.parse((Path(__file__).resolve().parent/'p51_shadow_inject.py').read_text())
        count=0
        for n in ast.walk(tree):
            if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
                    ('NULLGUARD_PATCHES','SUPPRESS_PATCHES') for t in n.targets):
                for rva,old,new,label in ast.literal_eval(n.value):
                    start=0x400000+rva
                    self.assertFalse(start<SITE+len(BEFORE) and SITE<start+len(bytes.fromhex(new)))
                    count+=1
        self.assertEqual(count,24)
        for start,raw,symbol,opcode in SITES.values():
            self.assertFalse(start<SITE+len(BEFORE) and SITE<start+len(raw))

    def test_hash_site_and_no_network_or_world_write_import(self):
        p=PE(BINARY);self.assertEqual(hashlib.sha256(p.data).hexdigest(),SANPK_SHA)
        self.assertEqual(p.read(SITE,6),BEFORE)
        meta=json.loads((BUILD/'unit_click.json').read_text())
        code=(BUILD/'unit_click.bin').read_bytes()
        self.assertEqual(hashlib.sha256(code).hexdigest(),meta['sha256'])
        self.assertLess(len(code),0x1000)
        from capstone import Cs,CS_ARCH_X86,CS_MODE_32
        calls=[i.op_str for i in Cs(CS_ARCH_X86,CS_MODE_32).disasm(code,CODE) if i.mnemonic=='call']
        self.assertEqual(len(calls),3) # one PC thunk and two reads of the same clock API
        self.assertEqual(calls.count('dword ptr [0x4fb2f8]'),2)

    def test_enabled_click_executes_original_epilogue_and_only_writes_mailbox(self):
        m=X86();m.click();r=m.r
        self.assertEqual(m.stopped,STOP)
        self.assertEqual(m.uc.reg_read(r.UC_X86_REG_ESP),STACK+0x8000+20)
        for reg,value in ((r.UC_X86_REG_EDI,0x111),(r.UC_X86_REG_ESI,0x222),
                          (r.UC_X86_REG_EBX,0x333),(r.UC_X86_REG_EBP,0x444)):
            self.assertEqual(m.uc.reg_read(reg),value)
        blob=bytes(m.uc.mem_read(MAILBOX,MAILBOX_SIZE));click=click_from_mailbox(blob)
        self.assertEqual(click['point'],[672,328]);self.assertEqual(click['core'],CORE)
        self.assertEqual(click['dimensions'],[101,202,64,32]);self.assertEqual(click['version'],2)
        self.assertTrue(all(MAILBOX<=a<MAILBOX+MAILBOX_SIZE or STACK<=a<STACK+0x10000 for a,n in m.writes))
        self.assertEqual(m.calls,['GetTickCount','GetTickCount'])

    def test_default_disabled_replays_original_cmp_preserves_registers(self):
        m=X86();initial=m.click(False)
        self.assertEqual(m.stopped,0x4988e9)
        for reg,value in initial.items():
            if reg!=m.r.UC_X86_REG_EFLAGS:self.assertEqual(m.uc.reg_read(reg),value)
        self.assertTrue(m.uc.reg_read(m.r.UC_X86_REG_EFLAGS)&0x40)
        self.assertIsNone(click_from_mailbox(bytes(m.uc.mem_read(MAILBOX,MAILBOX_SIZE))))
        self.assertEqual(m.calls,[])

    def test_expired_equal_deadline_and_clock_wrap(self):
        for now,deadline,expected in ((2000,2000,0x4988e9),(2001,2000,0x4988e9),
                                      (0xffffff00,0x300,STOP),(0x400,0x300,0x4988e9)):
            m=X86();m.now=now;m.click(deadline=deadline);self.assertEqual(m.stopped,expected)
        self.assertEqual(tick_age(0x100,0xffffff00),512)

    def test_modal_drag_widget_and_root_guards_pass_through(self):
        for a,v in ((VIEW+0x8da,1),(VIEW+0x210,1),(VIEW+0x7e2,1),(VIEW,0xdead),
                    (CORE,0xdead),(0x53b930,VIEW+4),(VIEW+0x3c,0)):
            m=X86();m.put(a,v);m.click();self.assertEqual(m.stopped,0x4988e9)
            self.assertEqual(m.get(MAILBOX+0xc),0)

    def test_odd_mailbox_publication_is_ignored(self):
        raw=bytearray(make_mailbox());struct.pack_into('<I',raw,12,1)
        self.assertIsNone(click_from_mailbox(bytes(raw)))

    def test_exact_original_diamond_hit_many_zoom_edges_and_centers(self):
        m=X86();r=m.r;generator=random.Random(53);count=0
        for tw,th in ((64,32),(48,24),(32,16),(16,8),(8,4),(256,128)):
            dims=(101,202,tw,th);m.uc.mem_write(DOC+0xf22,struct.pack('<4i',*dims))
            points=[(generator.randrange(0,102*tw),generator.randrange(0,203*th//2)) for _ in range(120)]
            points += [(x,y) for x in range(0,tw*2+1,max(1,tw//8)) for y in (0,th//4,th//2,th-1,th)]
            points += [(-1,-1),(-tw,-th),(101*tw,202*th//2)]
            for wx,wy in points:
                sp=STACK+0x8000;out=0x310000
                for i,value in enumerate((STOP,out,wx,wy)):m.put(sp+i*4,value)
                m.uc.reg_write(r.UC_X86_REG_ESP,sp);m.uc.reg_write(r.UC_X86_REG_ECX,VIEW)
                m.stopped=None;m.uc.emu_start(0x498591,STOP+1,count=500)
                self.assertEqual(m.stopped,STOP)
                actual=list(struct.unpack('<2i',m.uc.mem_read(out,8)))
                self.assertEqual(native_tile((wx,wy),dims),actual,(dims,wx,wy))
                count+=1
        self.assertGreater(count,1200)

    def test_partial_patch_write_rolls_back_without_world_changes(self):
        memory={SITE:BEFORE};first=[True]
        def read(a,n):return memory.get(a,b'')[:n]
        def write(a,raw):
            memory[a]=raw
            if first[0]:first[0]=False;raise OSError('synthetic torn write')
        with self.assertRaises(OSError):patch_transaction([(SITE,BEFORE,b'\x90'*6)],read,write)
        self.assertEqual(memory,{SITE:BEFORE})


if __name__=='__main__':unittest.main()
