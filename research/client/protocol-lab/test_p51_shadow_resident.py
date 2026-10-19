"""Behavioral x86 regressions for the actual resident/guard machine code."""
import json
from pathlib import Path
import struct
import unittest

from p51_shadow_resident import (build_blob, jump, active_d_threads, INSTALL_HOOKS,
                                 PATCHED_SITES, DWELL_MS, ENDPHASE_SENDER)
from shadow_stall_probe import frame_chain, stack_hits

CODE, BLOB, CORE, STACK, API, STOP = 0x200000, 0x201000, 0x300912, 0x600000, 0x700000, 0x800000
MAIN, WORKER = 276, 1000
NAMES = ('Sleep','GetCurrentThreadId','GetFileAttributesA','WaitForSingleObject',
         'GetTickCount','CreateFileA','WriteFile')
PTRS = {name:API+i*0x100 for i,name in enumerate(NAMES)}
BUILD = Path(__file__).parent/'resident-build'
V22_ACTIVE = (BUILD/'shadow_resident.bin').read_bytes()[0x420:0x424] == bytes.fromhex('8b4308')


class Machine:
    def __init__(self, tid=WORKER, trigger=True):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EAX, UC_X86_REG_ECX
        self.ESP,self.EIP,self.EAX,self.ECX=UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EAX,UC_X86_REG_ECX
        self.uc=Uc(UC_ARCH_X86,UC_MODE_32)
        for start,size in ((CODE,0x2000),(0x300000,0x2000),(0x400000,0x200000),
                           (STACK,0x10000),(API,0x1000),(STOP,0x1000)):
            self.uc.mem_map(start,size)
        self.meta=json.loads((BUILD/'shadow_resident.json').read_text())
        self.uc.mem_write(CODE,(BUILD/'shadow_resident.bin').read_bytes())
        self.uc.mem_write(BLOB,build_blob(CORE,MAIN,PTRS,'Z:\\flag','Z:\\receipt'))
        self.tid=tid;self.trigger=trigger;self.calls=[];self.receipts=[];self.endphase=[]
        self.on_sleep=None;self.on_d=None;self.on_wait=None;self.on_pump=None
        self.put(CORE+0x670,1)
        self.put(CORE+0x678,0xd4)
        self.uc.mem_write(0x44b8ca,jump(0x44b8ca,self.entry('resident_d_guard'),5))
        self.uc.hook_add(UC_HOOK_CODE,self.hook)

    def entry(self,name): return CODE+self.meta['entries'][name]
    def get(self,address): return struct.unpack('<I',self.uc.mem_read(address,4))[0]
    def put(self,address,value): self.uc.mem_write(address,struct.pack('<I',value))
    def ret(self,value=0,pop=0):
        sp=self.uc.reg_read(self.ESP)
        target=self.get(sp)
        self.uc.reg_write(self.ESP,sp+4+pop)
        self.uc.reg_write(self.EAX,value)
        self.uc.reg_write(self.EIP,target)

    def hook(self,uc,address,size,data):
        sp=uc.reg_read(self.ESP)
        if address==STOP:
            uc.emu_stop();return
        if address in PTRS.values():
            name=next(n for n,a in PTRS.items() if a==address)
            self.calls.append(name)
            if name=='Sleep':
                if self.on_sleep:self.on_sleep(self,self.get(sp+4))
                self.ret(0,4)
            elif name=='GetCurrentThreadId': self.ret(self.tid)
            elif name=='GetFileAttributesA': self.ret(0 if self.trigger else 0xffffffff,4)
            elif name=='GetTickCount': self.ret(0xffffff00)
            elif name=='CreateFileA': self.ret(77,28)
            elif name=='WriteFile':
                ptr,length=self.get(sp+8),self.get(sp+12)
                self.receipts.append(bytes(uc.mem_read(ptr,length)))
                self.ret(1,20)
            elif name=='WaitForSingleObject':
                if self.on_wait:self.on_wait(self,self.get(sp+4),self.get(sp+8))
                self.ret(0,8)
        elif address==0x44b8cf:
            self.calls.append('D_body')
            if self.on_d:self.on_d(self)
            self.ret()
        elif address==ENDPHASE_SENDER:
            self.calls.append('EndPhase')
            self.endphase.append(uc.reg_read(self.ECX))
            self.ret()
        elif address==0x444756:
            self.calls.append('UI_pump')
            if self.on_pump:self.on_pump(self)
            self.ret(1)

    def run(self,entry,count=40000,ecx=None):
        from unicorn.x86_const import UC_X86_REG_ECX
        self.uc.reg_write(self.ESP,STACK+0xf000)
        self.put(STACK+0xf000,STOP)
        self.put(STACK+0xf004,CORE)
        if ecx is not None:self.uc.reg_write(UC_X86_REG_ECX,ecx)
        self.uc.emu_start(self.entry(entry),0,count=count)


class ResidentTests(unittest.TestCase):
    def test_no_flag_never_calls_D(self):
        m=Machine(trigger=False)
        m.run('resident_worker')
        self.assertNotIn('D_body',m.calls)
        self.assertEqual(m.get(BLOB+0x18),0)

    def test_duplicate_callback_returns_without_work(self):
        m=Machine();m.put(BLOB+0x10,999)
        m.run('resident_worker')
        self.assertNotIn('D_body',m.calls)
        self.assertEqual(m.get(BLOB+0x28),1)
        self.assertEqual(m.uc.reg_read(m.ESP),STACK+0xf004)

    def test_D_requires_owner_and_excludes_reentry(self):
        for owner,inflight in ((999,0),(WORKER,1)):
            with self.subTest(owner=owner,inflight=inflight):
                m=Machine();m.put(BLOB+0x10,owner);m.put(BLOB+0x14,inflight)
                m.run('resident_d_guard')
                self.assertNotIn('D_body',m.calls)
                self.assertEqual(m.get(BLOB+0x28),1)

    def test_actual_return_then_UI_ack_before_next_D(self):
        m=Machine();waits=[0];seen=[]
        def body(m):
            seen.append(m.get(BLOB+0x24))
            self.assertEqual(m.get(BLOB+0x14),1)
            self.assertEqual(m.get(CORE-0x8aa),3)
            m.put(BLOB+0x1c,m.get(BLOB+0x1c)+1)
            m.put(BLOB+0x20,m.get(BLOB+0x20)+1)
            m.put(CORE+0x6bc,2)
        def sleep(m,ms):
            waits[0]+=1
            if waits[0]%20==0:m.put(CORE+0x6bc,0)
            if len(seen)>=5:m.uc.emu_stop()
        m.on_d=body;m.on_sleep=sleep
        m.run('resident_worker')
        self.assertEqual(seen,[0,1,2,3,4])
        self.assertGreaterEqual(waits[0],81)
        self.assertEqual(m.get(BLOB+0x18),5)
        self.assertEqual(m.get(BLOB+0x24),5)
        self.assertEqual(m.get(BLOB+0x28),0)
        self.assertTrue(all(r[:4]==b'SHG5' for r in m.receipts))

    def test_failed_sync_parks_and_never_retries(self):
        m=Machine();m.on_d=lambda m:m.put(CORE+0x6bc,2)
        m.run('resident_worker')
        self.assertEqual(m.calls.count('D_body'),1)
        self.assertEqual(m.get(BLOB+0x30),9)
        self.assertEqual(m.get(BLOB+0x34),1)

    def test_UI_owner_pumps_local_queue_instead_of_waiting(self):
        m=Machine(tid=MAIN);m.put(CORE+0x660,3)
        m.on_pump=lambda m:m.put(CORE+0x660,0)
        m.run('resident_ui_wait',ecx=CORE+0x654)
        self.assertEqual(m.calls.count('UI_pump'),1)
        self.assertNotIn('WaitForSingleObject',m.calls)
        self.assertEqual(m.uc.reg_read(m.ESP),STACK+0xf004)

    def test_worker_spurious_wake_does_not_complete_nonempty_queue(self):
        m=Machine();m.put(CORE+0x660,3);waits=[]
        def wait(m,event,timeout):
            waits.append((event,timeout))
            if len(waits)==40:m.put(CORE+0x660,0)
        m.on_wait=wait
        m.run('resident_ui_wait',ecx=CORE+0x654)
        self.assertEqual(waits,[(0xd4,0xffffffff)]*40)
        self.assertNotIn('UI_pump',m.calls)
        self.assertEqual(m.uc.reg_read(m.ESP),STACK+0xf004)

    def test_recovery_holds_second_worker_until_explicit_release(self):
        m=Machine();m.put(BLOB+0x64,292);m.put(CORE+0x660,0)
        m.run('resident_ui_return',count=1000)
        self.assertNotEqual(m.uc.reg_read(m.EIP),STOP)
        m.put(BLOB+0x64,WORKER)
        m.uc.emu_start(m.uc.reg_read(m.EIP),0,count=1000)
        self.assertEqual(m.uc.reg_read(m.EIP),STOP)

    def test_long_UI_wait_has_no_abort_or_wall_clock_fuse(self):
        m=Machine();m.put(CORE+0x660,1)
        m.run('resident_ui_wait',count=60000,ecx=CORE+0x654)
        self.assertGreater(m.calls.count('WaitForSingleObject'),100)
        self.assertEqual(m.get(BLOB+0x34),0)
        self.assertNotIn('GetTickCount',m.calls)


class V2HooksetTests(unittest.TestCase):
    """v2 = opening-safe single-driver hook set (2026-10-18 incidents)."""

    def test_hookset_excludes_opening_paths(self):
        self.assertEqual(PATCHED_SITES,(0x44b8be,0x44b8ca,0x44b924,0x44bb10))
        self.assertNotIn(0x44474e,PATCHED_SITES)  # spawner call must execute
        self.assertNotIn(0x44a8d9,PATCHED_SITES)  # no main-UI wait hook

    def test_hookset_before_bytes_are_the_df9b5225_originals(self):
        expect={0x44b8be:'8b4c2404e8',0x44b8ca:'b8881f4f00',
                0x44b924:'6a08899ec4060000',0x44bb10:'8dbe87000000'}
        for a,orig,entry,label in INSTALL_HOOKS:
            self.assertEqual(orig,expect[a],label)

    def test_hookset_entries_exist_in_payload(self):
        meta=json.loads((BUILD/'shadow_resident.json').read_text())
        for a,orig,entry,label in INSTALL_HOOKS:
            self.assertIn(entry,meta['entries'],label)

    def test_native_spawn_at_armed_prefire_is_absorbed(self):
        # Post-start/pre-fire: the tick may spawn its own callback; the owner
        # gate must absorb it as a clean duplicate (no D, no state disturbed).
        m=Machine();m.put(BLOB+0x10,555)
        m.run('resident_worker')
        self.assertNotIn('D_body',m.calls)
        self.assertEqual(m.get(BLOB+0x28),1)
        self.assertEqual(m.get(BLOB+0x18),0)


class V21DwellTests(unittest.TestCase):
    """v2.1: yield between rounds so the game's own render/tick loop runs."""

    def test_dwell_field_written_to_blob(self):
        b = build_blob(CORE, MAIN, PTRS, 'Z:\\flag', 'Z:\\receipt')
        self.assertEqual(struct.unpack_from('<I', b, 0x1b0)[0], DWELL_MS)
        b2 = build_blob(CORE, MAIN, PTRS, 'Z:\\flag', 'Z:\\receipt', dwell_ms=250)
        self.assertEqual(struct.unpack_from('<I', b2, 0x1b0)[0], 250)

    def test_patched_bin_has_site_jump_and_gadget(self):
        code = (BUILD/'shadow_resident.bin').read_bytes()
        self.assertEqual(code[0xd1], 0xe9)  # worker_wait_ui -> gadget
        self.assertEqual(code[0x400:0x406], bytes.fromhex('ffb3b0010000'))
        self.assertEqual(code[0x406:0x409], bytes.fromhex('ff5338'))

    def test_post_round_dwell_reaches_sleep(self):
        m = Machine()
        sleeps = []
        def body(mm):
            mm.put(BLOB+0x1c, mm.get(BLOB+0x1c)+1)
            mm.put(BLOB+0x20, mm.get(BLOB+0x20)+1)
            mm.put(CORE+0x6bc, 2)  # completion; gates stay closed
        m.on_d = body
        m.on_sleep = lambda mm, ms: sleeps.append(ms)
        m.run('resident_worker', count=6000)
        self.assertIn(DWELL_MS, sleeps)


@unittest.skipUnless(V22_ACTIVE, 'v2.2 endphase payload not active (v2.1 shipped for pure-observer test)')
class V22EndPhaseTests(unittest.TestCase):
    """v2.2: call the game's own EndPhase sender once per changed round deadline."""

    @staticmethod
    def _drive(mm):
        mm.put(BLOB+0x1c, mm.get(BLOB+0x1c)+1)
        mm.put(BLOB+0x20, mm.get(BLOB+0x20)+1)
        mm.put(CORE+0x6bc, 2)

    def test_endphase_fires_on_new_round_deadline(self):
        m = Machine()
        m.put(CORE-0x8a6, 0x00123456)     # G+0x6c: round deadline of a new round
        m.on_d = self._drive
        m.run('resident_worker', count=5000)
        self.assertEqual(m.calls.count('EndPhase'), 1)
        self.assertEqual(m.endphase[0], CODE+0x600)          # fake this
        self.assertEqual(m.get(CODE+0x600+0x3c), CORE-0x912)  # +0x3c = G
        self.assertEqual(m.get(CODE+0x600+0x8a6), 0)          # +0x8a6 = 0
        self.assertEqual(m.get(BLOB+0x1b8), 0x00123456)

    def test_endphase_skips_unchanged_deadline(self):
        m = Machine()
        m.put(CORE-0x8a6, 0x00123456)
        m.put(BLOB+0x1b8, 0x00123456)
        m.on_d = self._drive
        m.run('resident_worker', count=5000)
        self.assertEqual(m.calls.count('EndPhase'), 0)

    def test_gadget_still_dwells_after_endphase(self):
        m = Machine()
        m.put(CORE-0x8a6, 0x00123456)
        sleeps = []
        m.on_sleep = lambda mm, ms: sleeps.append(ms)
        m.on_d = self._drive
        m.run('resident_worker', count=5000)
        self.assertIn(DWELL_MS, sleeps)


class DiagnosticTests(unittest.TestCase):
    def test_deep_stack_hit_is_not_truncated(self):
        b=bytearray(12000)
        for i in range(60):struct.pack_into('<I',b,i*4,0x410000+i)
        struct.pack_into('<I',b,9968,0x44b8c7)
        self.assertEqual(stack_hits(b,0x123000)[-1]['offset'],9968)

    def test_stale_raw_hit_does_not_prove_live_D(self):
        c={'threads':[{'tid':1,'frames':[{'return':'0x4170ed'}],
                       'stack_hits':[{'value':'0x44b8c7'}]},
                      {'tid':2,'frames':[{'return':'0x44b8c7'}]}]}
        self.assertEqual(active_d_threads(c),[2])

    def test_frame_chain_honors_stack_boundary_and_cycles(self):
        memory={100:struct.pack('<II',108,0x410000),108:struct.pack('<II',100,0x420000)}
        self.assertEqual(len(frame_chain(lambda a,n:memory.get(a,b''),100,100,116)),2)
        self.assertEqual(frame_chain(lambda a,n:memory.get(a,b''),100,100,104),[])


if __name__=='__main__': unittest.main()
