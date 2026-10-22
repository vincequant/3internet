"""Fake-memory tests for the bounded KOEINM payload sample and journal."""
import hashlib
import json
import struct
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from network_payloads import (
    BUDGET_S, CONTEXT_END_RVA, CONTEXT_RVA, CORE_ANCHOR, CORE_VTABLE, ENTRY_SIZE,
    HEAD_OFFSET, KOEINM_SHA, MAX_FILE_BYTES, MAX_PAYLOAD, MAX_QUEUE_ENTRIES, MAX_SAMPLE_EVENTS,
    MAX_SAMPLE_PAYLOAD, MAX_SESSION_BYTES, SANPK_BUILD, USER_HIGH, NetworkPayloadObserver, PayloadJournal,
    _pe_fields, resolve_network_module,
)

NOW = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
BASE = 0x400000
ARRAY = 0x210000
PAYLOAD = 0x310000
BINDING = {
    'pid': 1096,
    'created': 134359988899137490,
    'image': r'C:\sgi\run-3.5\3I\SANPK.exe',
    'core': 54602506,
    'build': SANPK_BUILD,
    'source_id': 'VKQUANT',
}
IDENTITY = {'pid': 1096, 'path': BINDING['image'], 'creation_filetime': BINDING['created']}
DLL = r'C:\sgi\run-3.5\3I\KOEINM.dll'


class FakeMemory:
    """Test double. Not a process, and not a way around the DLL hash."""

    def __init__(self, regions, identity=None, script=None, clock=None):
        self.regions = {start: bytearray(blob) for start, blob in regions.items()}
        self.identity = dict(IDENTITY if identity is None else identity)
        self.h = 1
        self.calls = []
        self.script = script or []
        self.clock = clock
        self.fake = True

    def read(self, address, size):
        self.calls.append((address, size))
        if self.clock is not None:
            self.clock['n'] = self.clock.get('n', 0) + 1
            if self.clock['n'] >= self.clock['trip']:
                self.clock['t'] = self.clock['t'] + 1
        for pred, value in self.script:
            if pred(address, size):
                if value is None:
                    raise OSError('programmed read failure')
                return value
        for start, blob in self.regions.items():
            if start <= address and address + size <= start + len(blob):
                return bytes(blob[address - start:address - start + size])
        raise OSError('unmapped')


def pe_image(buf=0x1B000, image_size=None, machine=0x14c, magic=0x10b, mz=b'MZ', e_lfanew=0x80):
    image_size = buf if image_size is None else image_size
    blob = bytearray(buf)
    blob[0:2] = mz
    struct.pack_into('<I', blob, 0x3c, e_lfanew)
    if 0 < e_lfanew and e_lfanew + 84 <= buf:
        blob[e_lfanew:e_lfanew + 4] = b'PE\0\0'
        struct.pack_into('<H', blob, e_lfanew + 4, machine)
        struct.pack_into('<H', blob, e_lfanew + 24, magic)
        struct.pack_into('<I', blob, e_lfanew + 24 + 56, image_size)
    return blob


def put_head(image, array, count, read_index, alt_array=0, alt_count=0):
    struct.pack_into('<5I', image, CONTEXT_RVA + HEAD_OFFSET, array, count, read_index, alt_array, alt_count)


def entry_bytes(metadata, pointer, length):
    return struct.pack('<3I', metadata, pointer, length)


def module_for(image, base=BASE):
    headers, error = _pe_fields(FakeMemory({base: image}), base)
    if error:
        raise AssertionError(error)
    return {
        'status': 'ok', 'base': base, 'path': DLL, 'sha256': KOEINM_SHA,
        'context': base + CONTEXT_RVA, 'fake': True, 'headers': headers,
        'read_only': True, 'no_target_calls': True,
    }


def observer(memory, module, binding=None, clock=None):
    mono = (lambda: clock['t']) if clock is not None else None
    return NetworkPayloadObserver(
        memory, BINDING if binding is None else binding, module,
        monotonic=mono, clock=lambda: NOW)


def lines(root):
    rows = []
    for path in sorted(root.rglob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if line:
                rows.append((path, json.loads(line)))
    return rows


def nth_read(address, size, hit):
    seen = {'n': 0}

    def pred(addr, width):
        if addr == address and width == size:
            seen['n'] += 1
            return seen['n'] == hit
        return False
    return pred


class ResolveTests(unittest.TestCase):
    def test_reconnect_build_keeps_actual_digest_and_unknown_file_is_rejected(self):
        image = bytes(pe_image())
        digest = hashlib.sha256(image).hexdigest()
        for version in ('R1', 'R2'):
            with self.subTest(version=version), patch('network_payloads.KOEINM_RECONNECT_' + version + '_SHA', digest):
                found = resolve_network_module(FakeMemory({BASE: image}),
                    enumerate_modules=lambda handle: [(BASE, DLL)], read_file=lambda path: image)
                self.assertEqual(found['status'], 'ok')
                self.assertEqual(found['sha256'], digest)
                self.assertNotEqual(found['sha256'], KOEINM_SHA)
                self.assertTrue(found['fake'])
                self.assertTrue(found['no_target_calls'])
                rejected = resolve_network_module(FakeMemory({BASE: image}),
                    enumerate_modules=lambda handle: [(BASE, DLL)], read_file=lambda path: image + b'x')
                self.assertEqual(rejected['reason'], 'dll_sha')

    def test_unknown_results_do_not_guess_or_throw(self):
        image = pe_image()
        calls = []

        def read_file(path):
            calls.append(path)
            return bytes(image)

        class Bare:
            h = None
            identity = dict(IDENTITY)

        missing = resolve_network_module(Bare())
        self.assertEqual(missing['status'], 'unknown')
        self.assertFalse(missing['fake'])

        def enumerate(modules):
            return resolve_network_module(
                FakeMemory({BASE: image}), enumerate_modules=lambda handle: modules, read_file=read_file)

        self.assertEqual(enumerate([(BASE, r'C:\sgi\OTHER.dll')])['reason'], 'not_found')
        self.assertEqual(calls, [])
        duplicate = enumerate([(BASE, DLL), (BASE + 0x200000, DLL.upper())])
        self.assertEqual(duplicate['reason'], 'duplicate')
        self.assertTrue(duplicate['fake'])
        self.assertEqual(calls, [])
        self.assertEqual(enumerate([(1, 'koeinm.dll')])['reason'], 'context_range')
        def boom(handle):
            raise RuntimeError('boom')

        raised = resolve_network_module(FakeMemory({}), enumerate_modules=boom)
        self.assertEqual(raised['status'], 'unknown')
        self.assertEqual(raised['reason'], 'exception')

        too_big = resolve_network_module(
            FakeMemory({BASE: image}),
            enumerate_modules=lambda handle: [(BASE, DLL)],
            read_file=lambda path: b'x' * (MAX_FILE_BYTES + 1))
        self.assertEqual(too_big['reason'], 'file_too_large')
        unreadable = resolve_network_module(
            FakeMemory({BASE: image}),
            enumerate_modules=lambda handle: [(BASE, DLL)],
            read_file=lambda path: (_ for _ in ()).throw(OSError('no')))
        self.assertEqual(unreadable['reason'], 'file_unreadable')

        rejected = resolve_network_module(
            FakeMemory({BASE: image}),
            enumerate_modules=lambda handle: [(BASE, DLL)],
            read_file=read_file)
        self.assertEqual(rejected['reason'], 'dll_sha')
        self.assertTrue(rejected['fake'])
        self.assertNotEqual(rejected.get('sha256'), KOEINM_SHA)
        self.assertEqual(calls, [DLL])

    def test_matching_sha_still_checks_loaded_image_and_marks_fake(self):
        image = bytes(pe_image())
        digest = hashlib.sha256(image).hexdigest()

        def resolve(mem_image, file_bytes=image, base=BASE):
            with patch('network_payloads.KOEINM_SHA', digest):
                return resolve_network_module(
                    FakeMemory({base: mem_image}),
                    enumerate_modules=lambda handle: [(base, DLL)],
                    read_file=lambda path: file_bytes)

        found = resolve(image)
        self.assertEqual(found['status'], 'ok')
        self.assertTrue(found['fake'])
        self.assertEqual(found['sha256'], digest)
        self.assertEqual(found['base'], BASE)
        self.assertEqual(found['path'], DLL)
        self.assertEqual(found['context'], BASE + CONTEXT_RVA)
        self.assertEqual(found['headers']['machine'], 0x14c)
        self.assertEqual(found['headers']['magic'], 0x10b)
        self.assertLessEqual(found['headers']['context_end'], USER_HIGH)
        self.assertGreater(found['headers']['size_of_image'], CONTEXT_END_RVA)
        self.assertTrue(found['read_only'])
        self.assertTrue(found['no_target_calls'])

        self.assertEqual(resolve(pe_image(mz=b'XX'))['reason'], 'not_mz')
        self.assertEqual(resolve(pe_image(machine=0x8664))['reason'], 'machine')
        self.assertEqual(resolve(pe_image(magic=0x20b))['reason'], 'pe32')
        self.assertEqual(resolve(pe_image(image_size=0x1000))['reason'], 'size_of_image')
        high = 0x7FFF0000
        self.assertGreater(CONTEXT_END_RVA, USER_HIGH - high)
        self.assertEqual(resolve(image, base=high)['reason'], 'context_range')


class ObserverTests(unittest.TestCase):
    def test_budget_resume_reaches_late_primary_and_alternate_without_duplicate_events(self):
        clock={'t':0.0};counts={}
        memory,module,obs=self.build([b'a',b'b',b'c',b'd'],count=3,
                                    alt_array=ARRAY+3*ENTRY_SIZE,alt_count=1)
        def spend_on_stable_payload(address,size):
            if PAYLOAD <= address < PAYLOAD+4:
                counts[address]=counts.get(address,0)+1
                if counts[address]%2==0:clock['t']+=BUDGET_S*2
            return False
        memory.script=[(spend_on_stable_payload,b'')]
        obs._monotonic=lambda:clock['t']
        results=[obs.poll() for _ in range(4)]
        events=[e for r in results for e in r['events']]
        self.assertEqual([e['raw_hex'] for e in events],[b'a'.hex(),b'b'.hex(),b'c'.hex(),b'd'.hex()])
        self.assertEqual([e['queue'] for e in events],['primary','primary','primary','alternate'])
        self.assertTrue(all(r['budget_gap'] for r in results))
        self.assertTrue(all(not obs.poll()['events'] for _ in range(4)))

    def build(self, payloads, **kwargs):
        per = []
        blob = bytearray()
        entries = bytearray()
        metadata = kwargs.get('metadata', 0x11223344)
        for index, payload in enumerate(payloads):
            pointer = PAYLOAD + len(blob)
            blob.extend(payload)
            entries.extend(entry_bytes(metadata + index, pointer, len(payload)))
            per.append(pointer)
        image = pe_image()
        count = kwargs.get('count', len(payloads))
        array = kwargs.get('array', ARRAY if count else 0)
        put_head(image, array, count, kwargs.get('read_index', 0), kwargs.get('alt_array', 0), kwargs.get('alt_count', 0))
        regions = {BASE: image}
        if entries and count:
            regions[array] = bytes(entries)
        if blob:
            regions[PAYLOAD] = bytes(blob)
        binding = kwargs.get('binding') or BINDING
        regions[CORE_ANCHOR] = struct.pack('<I', binding['core'])
        regions[binding['core']] = struct.pack('<I', CORE_VTABLE)
        memory = FakeMemory(regions, script=kwargs.get('script'), clock=kwargs.get('clock'), identity=kwargs.get('identity'))
        module = kwargs.get('module') or module_for(image)
        return memory, module, observer(memory, module, kwargs.get('binding'), kwargs.get('clock'))

    def test_stable_payload_keeps_exact_bytes_and_sha(self):
        payload = bytes([0x10, 0x02, 0x00, 0x43, 0x4d, 0x44, 0xff])
        memory, module, obs = self.build([payload])
        before = deepcopy(module)
        result = obs.poll()
        self.assertEqual(module, before)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['event_count'], 1)
        self.assertEqual(result['gaps'], [])
        self.assertEqual(result['drop_count'], 0)
        self.assertFalse(result['absence_means_no_command'])
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['completeness'], 'unknown')
        self.assertIn('aba_reuse_between_polls_is_not_observable', result['limitations'])
        event = result['events'][0]
        self.assertEqual(event['raw_hex'], payload.hex())
        self.assertEqual(event['raw_sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(bytes.fromhex(event['raw_hex']), payload)
        self.assertEqual(event['metadata_raw'], 0x11223344)
        self.assertEqual(event['payload_length'], len(payload))
        self.assertEqual(event['entry_index'], 0)
        self.assertEqual(event['queue'], 'primary')
        self.assertTrue(event['fake'])
        self.assertIsNone(event['decoded_action'])
        self.assertIsNone(event['actor_force_id'])
        self.assertIsNone(event['target_lord_id'])
        self.assertFalse(event['submission_or_execution_verified'])
        self.assertFalse(event['action_training_eligible'])
        self.assertTrue(event['read_only'])
        self.assertTrue(event['no_target_calls'])
        self.assertEqual(obs.public_status()['events'], 1)
        self.assertLessEqual(obs.public_status()['cached_keys'], 512)

    def test_changed_reads_and_short_read_are_rejected(self):
        payload = b'\x20\x21\x22\x23'
        cases = [
            ('changed_entry', nth_read(ARRAY, ENTRY_SIZE, 2), b'\x00' * ENTRY_SIZE),
            ('changed_head', nth_read(BASE + CONTEXT_RVA + HEAD_OFFSET, 20, 2), b'\x00' * 20),
            ('changed_payload', nth_read(PAYLOAD, len(payload), 2), b'\x99' * len(payload)),
            ('changed_module_header', nth_read(BASE, 0x40, 2), b'NZ' + b'\x00' * 0x3e),
            ('short_read', lambda addr, size: addr == PAYLOAD, b'\x20'),
        ]
        for reason, pred, value in cases:
            with self.subTest(reason=reason):
                memory, module, obs = self.build([payload], script=[(pred, value)])
                result = obs.poll()
                self.assertEqual(result['events'], [])
                self.assertTrue(any(gap['reason'] == reason or gap['reason'] == 'short_read' for gap in result['gaps']))
                if reason == 'short_read':
                    self.assertEqual(result['gaps'][0]['reason'], 'short_read')
                else:
                    self.assertIn(reason, [gap['reason'] for gap in result['gaps']])
                self.assertNotIn(payload.hex(), json.dumps(result['events']))

        memory, module, obs = self.build([payload])
        memory.regions[BASE][0:2] = b'NZ'
        refused = obs.poll()
        self.assertEqual(refused['events'], [])
        self.assertEqual(refused['status'], 'unknown')
        self.assertEqual(refused['reason'], 'changed_module_header')
        self.assertNotIn((PAYLOAD, len(payload)), memory.calls)

    def test_clear_retains_cursor_without_reading_freed_slots_then_queue_refills(self):
        clock = {'t': 0.0, 'trip': float('inf')}
        memory, module, obs = self.build([b'new'], clock=clock)
        put_head(memory.regions[BASE], ARRAY, 0, 2)
        for _ in range(4):
            result = obs.poll()
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['events'], [])
            self.assertEqual(result['gaps'], [])
        self.assertNotIn((ARRAY, ENTRY_SIZE), memory.calls)
        self.assertNotIn((PAYLOAD, 3), memory.calls)
        # During refill the count can remain below the previous read cursor.
        put_head(memory.regions[BASE], ARRAY, 1, 2)
        result = obs.poll()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([e['raw_hex'] for e in result['events']], [b'new'.hex()])
        self.assertEqual(result['events'][0]['read_index'], 2)
        self.assertFalse(any(ARRAY < a < ARRAY + 2 * ENTRY_SIZE for a, _ in memory.calls))

    def test_cleared_primary_does_not_starve_live_alternate_queue(self):
        memory, module, obs = self.build([b'next'], clock={'t': 0.0, 'trip': float('inf')})
        put_head(memory.regions[BASE], 0, 0, 2, ARRAY, 1)
        result = obs.poll()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([(e['queue'], e['raw_hex']) for e in result['events']],
                         [('alternate', b'next'.hex())])

    def test_each_head_scalar_remains_bounded_after_cursor_fix(self):
        for count, cursor, alternate_count in ((MAX_QUEUE_ENTRIES + 1, 0, 0),
                                               (0, MAX_QUEUE_ENTRIES + 1, 0),
                                               (0, 2, MAX_QUEUE_ENTRIES + 1)):
            with self.subTest(count=count, cursor=cursor, alternate_count=alternate_count):
                memory, module, obs = self.build([], count=count, read_index=cursor,
                                                alt_count=alternate_count, clock={'t': 0.0, 'trip': float('inf')})
                result = obs.poll()
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['reason'], 'queue_bounds')
                self.assertEqual(result['events'], [])
                self.assertFalse(any(s == ENTRY_SIZE for _, s in memory.calls))

    def test_limits_leave_gaps_without_crashing(self):
        payload = b'\x30\x31'
        memory, module, obs = self.build([], count=257, array=ARRAY)
        result = obs.poll()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['reason'], 'queue_bounds')
        self.assertEqual(result['events'], [])
        self.assertFalse(any(size == ENTRY_SIZE for _, size in memory.calls))

        memory, module, obs = self.build([b'\xff' * (MAX_PAYLOAD + 1)])
        # build() places the oversized payload, but the entry length is what the queue says.
        # Rewrite the one entry so its length field is over the cap and its pointer stays in range.
        memory.regions[ARRAY][:] = entry_bytes(1, PAYLOAD, MAX_PAYLOAD + 1)
        result = obs.poll()
        self.assertEqual(result['events'], [])
        self.assertIn('payload_length', [gap['reason'] for gap in result['gaps']])

        memory, module, obs = self.build([payload])
        memory.regions[ARRAY][:] = entry_bytes(1, 0x7FFFFF00, 0x200)
        result = obs.poll()
        self.assertEqual(result['events'], [])
        self.assertIn('address', [gap['reason'] for gap in result['gaps']])

        memory, module, obs = self.build([payload])
        memory.regions[ARRAY][:] = entry_bytes(1, 0x40, 4)
        result = obs.poll()
        self.assertIn('address', [gap['reason'] for gap in result['gaps']])

        clock = {'t': 0.0, 'n': 0, 'trip': 1}
        memory, module, obs = self.build([payload], clock=clock)
        result = obs.poll()
        self.assertTrue(result['budget_gap'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['events'], [])
        self.assertIn('budget', [gap['reason'] for gap in result['gaps']])
        self.assertGreaterEqual(result['drop_count'], 1)
        self.assertLess(BUDGET_S, 1)

        wide = [b'\x41' * MAX_PAYLOAD] * 20
        # Test byte/event limits independently of host scheduling; the
        # separate advancing-clock case above exercises the 5ms time limit.
        memory, module, obs = self.build(wide, clock={'t': 0.0, 'trip': float('inf')})
        result = obs.poll()
        self.assertEqual(len(result['events']), MAX_SAMPLE_PAYLOAD // MAX_PAYLOAD)
        self.assertTrue(result['partial'])
        self.assertIn('payload_total', [gap['reason'] for gap in result['gaps']])
        self.assertGreaterEqual(result['drop_count'], 1)
        self.assertLessEqual(sum(event['payload_length'] for event in result['events']), MAX_SAMPLE_PAYLOAD)
        self.assertEqual(sum(1 for _, size in memory.calls if size == MAX_PAYLOAD), (MAX_SAMPLE_PAYLOAD // MAX_PAYLOAD) * 2)

        many = [bytes([index & 0xff]) for index in range(MAX_SAMPLE_EVENTS + 1)]
        memory, module, obs = self.build(many, clock={'t': 0.0, 'trip': float('inf')})
        first = obs.poll()
        second = obs.poll()
        third = obs.poll()
        self.assertEqual(len(first['events']), MAX_SAMPLE_EVENTS)
        self.assertGreaterEqual(first['drop_count'], 1)
        self.assertIn('event_limit', [gap['reason'] for gap in first['gaps']])
        self.assertEqual([event['entry_index'] for event in second['events']], [MAX_SAMPLE_EVENTS])
        self.assertEqual(third['events'], [])

    def test_dedup_reappear_and_new_binding(self):
        payload = b'\x51\x52\x53'
        memory, module, obs = self.build([payload])
        binding = deepcopy(BINDING)
        first = obs.poll()
        self.assertEqual(len(first['events']), 1)
        second = obs.poll()
        self.assertEqual(second['events'], [])
        self.assertEqual(second['drop_count'], 0)
        head = CONTEXT_RVA + HEAD_OFFSET
        struct.pack_into('<5I', memory.regions[BASE], head, 0, 0, 0, 0, 0)
        empty = obs.poll()
        self.assertEqual(empty['events'], [])
        self.assertEqual(empty['status'], 'ok')
        struct.pack_into('<5I', memory.regions[BASE], head, ARRAY, 1, 0, 0, 0)
        again = obs.poll()
        self.assertEqual(len(again['events']), 1)
        self.assertEqual(again['events'][0]['raw_sha256'], first['events'][0]['raw_sha256'])
        other = observer(memory, module)
        self.assertEqual(len(other.poll()['events']), 1)
        moved = dict(binding)
        moved['pid'] = 1097
        moved['created'] = binding['created'] + 1
        memory.identity['pid'] = 1097
        memory.identity['creation_filetime'] = moved['created']
        rebound = observer(memory, module, moved)
        self.assertEqual(len(rebound.poll()['events']), 1)
        self.assertEqual(obs.poll()['status'], 'unknown')
        self.assertEqual(binding, BINDING)

    def test_unsupported_build_module_and_dll_sha_do_not_read(self):
        payload = b'\x61'
        memory, module, obs = self.build([payload])
        bad_build = dict(BINDING)
        bad_build['build'] = 'ab' * 32
        refused = observer(memory, module, bad_build)
        result = refused.poll()
        self.assertEqual(result['reason'], 'unsupported_build')
        self.assertEqual(result['events'], [])
        self.assertEqual(memory.calls, [])

        memory, module, obs = self.build([payload])
        wrong = deepcopy(module)
        wrong['sha256'] = '0' * 64
        result = observer(memory, wrong).poll()
        self.assertEqual(result['reason'], 'module')
        self.assertEqual(memory.calls, [])

        memory, module, obs = self.build([payload])
        named = deepcopy(module)
        named['path'] = r'C:\sgi\run-3.5\3I\not-koeinm.dll'
        result = observer(memory, named).poll()
        self.assertEqual(result['reason'], 'module')
        self.assertEqual(memory.calls, [])


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.payload = b'\x10\x02CMD'
        image = pe_image()
        put_head(image, ARRAY, 1, 0)
        self.module = module_for(image)
        self.event_memory, self.module, self.obs = ObserverTests().build([self.payload])
        self.poll = self.obs.poll()

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_roll_error_limits_and_unknown_labels(self):
        journal = PayloadJournal(self.root, BINDING)
        poll = deepcopy(self.poll)
        module = deepcopy(self.module)
        binding = deepcopy(BINDING)
        poll['events'][0]['decoded_action'] = 'attack'
        poll['events'][0]['actor_force_id'] = 3
        poll['events'][0]['target_lord_id'] = 9
        poll['events'][0]['submission_or_execution_verified'] = True
        poll['events'][0]['action_training_eligible'] = True
        snapshot = deepcopy(poll)
        module_snapshot = deepcopy(module)
        journal.ingest(poll, module, NOW)
        self.assertEqual(poll, snapshot)
        self.assertEqual(module, module_snapshot)
        self.assertEqual(binding, BINDING)
        saved = lines(journal.root)
        self.assertEqual(len(saved), 1)
        row = saved[0][1]
        self.assertEqual(row['kind'], 'network_payload_observation')
        self.assertEqual(row['raw_hex'], self.payload.hex())
        self.assertEqual(row['raw_sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(row['build'], SANPK_BUILD)
        self.assertEqual(row['source_id'], 'VKQUANT')
        self.assertEqual(row['core'], BINDING['core'])
        self.assertEqual(row['module']['sha256'], KOEINM_SHA)
        self.assertEqual(row['target']['pid'], BINDING['pid'])
        self.assertEqual(row['target']['creation_filetime'], BINDING['created'])
        self.assertIsNone(row['decoded_action'])
        self.assertIsNone(row['actor_force_id'])
        self.assertIsNone(row['target_lord_id'])
        self.assertFalse(row['submission_or_execution_verified'])
        self.assertFalse(row['action_training_eligible'])
        self.assertFalse(row['absence_means_no_command'])
        self.assertEqual(row['coverage'], 'partial')
        self.assertEqual(row['completeness'], 'unknown')
        self.assertTrue(row['read_only'])
        self.assertTrue(row['no_target_calls'])
        self.assertFalse(row['capture_session_is_match_id'])
        self.assertNotIn('match_id', row)
        status = journal.public_status()
        self.assertEqual(status['events'], 1)
        self.assertEqual(status['samples'], 1)
        self.assertEqual(status['directory_name'], 'native-payload-observations')
        self.assertNotIn('game_stopped', status)
        self.assertNotIn('game_started', status)

        quiet = dict(self.poll)
        quiet['events'] = []
        quiet['gaps'] = []
        quiet['drop_count'] = 2
        journal.ingest(quiet, module, NOW)
        self.assertEqual(len(lines(journal.root)), 1)
        self.assertEqual(journal.public_status()['samples'], 2)
        self.assertEqual(journal.public_status()['events'], 1)
        self.assertEqual(journal.public_status()['drops'], 2)

        size = saved[0][0].stat().st_size
        journal.close()
        self.assertTrue(journal.public_status()['journal_closed'])
        rolled = PayloadJournal(self.root, BINDING, max_segment_bytes=size)
        rolled.ingest(self.poll, module, NOW)
        first_path = next(rolled.root.rglob('%s-seg-0001.jsonl' % rolled.public_status()['capture_session_id']))
        first_bytes = first_path.read_bytes()
        rolled.ingest(self.poll, module, NOW)
        self.assertEqual(first_path.read_bytes(), first_bytes)
        session_files = sorted(rolled.root.rglob('%s-seg-*.jsonl' % rolled.public_status()['capture_session_id']))
        self.assertEqual(len(session_files), 2)
        self.assertNotEqual(rolled.public_status()['capture_session_id'], status['capture_session_id'])

        huge = deepcopy(self.poll)
        huge['events'][0]['raw_hex'] = 'aa' * 70000
        huge['events'][0]['raw_sha256'] = 'bb' * 32
        limited = PayloadJournal(self.root, BINDING)
        limited.ingest(huge, module, NOW)
        self.assertIsNotNone(limited.public_status()['write_error'])
        self.assertEqual(limited.public_status()['events'], 0)
        self.assertNotIn('aa' * 100, ''.join(path.read_text(encoding='utf-8') for path in limited.root.rglob('*.jsonl')))

        blocked = self.root / 'not-a-directory'
        blocked.write_text('x', encoding='utf-8')
        broken = PayloadJournal(blocked, BINDING)
        broken.ingest(self.poll, module, NOW)
        self.assertIsNotNone(broken.public_status()['write_error'])
        self.assertEqual(broken.public_status()['events'], 0)

        bad = dict(BINDING)
        bad['build'] = '00' * 32
        rejected = PayloadJournal(self.root, bad)
        rejected.ingest(self.poll, module, NOW)
        self.assertEqual(rejected.public_status()['write_error'], 'binding')
        self.assertEqual(rejected.public_status()['events'], 0)
        journal.close()
        rolled.close()
        limited.close()
        broken.close()
        rejected.close()

    def test_gap_dedup_and_binding_isolation(self):
        module = self.module
        journal = PayloadJournal(self.root, BINDING)
        gap = {
            'status': 'partial', 'events': [], 'gaps': [{'sample': 1, 'reason': 'budget'}],
            'drop_count': 1, 'sample': 1, 'binding': self.poll['binding'],
            'generation': self.poll['generation'], 'module': self.poll['module'],
            'capture_session_is_match_id': False,
        }
        journal.ingest(deepcopy(gap), module, NOW)
        journal.ingest(deepcopy(gap), module, NOW)
        saved = lines(journal.root)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][1]['kind'], 'network_payload_gap')
        self.assertEqual(saved[0][1]['reason'], 'budget')
        self.assertIsNone(saved[0][1]['decoded_action'])
        self.assertFalse(saved[0][1]['absence_means_no_command'])
        self.assertEqual(journal.public_status()['gaps'], 1)
        self.assertEqual(journal.public_status()['drops'], 2)
        clear = {
            'status': 'ok', 'events': [], 'gaps': [], 'drop_count': 0, 'sample': 3,
            'binding': self.poll['binding'], 'generation': self.poll['generation'],
            'module': self.poll['module'], 'capture_session_is_match_id': False,
        }
        journal.ingest(clear, module, NOW)
        self.assertEqual(len(lines(journal.root)), 1)
        journal.ingest(deepcopy(gap), module, NOW)
        self.assertEqual(len(lines(journal.root)), 2)

        other_binding = dict(BINDING)
        other_binding['pid'] = 50
        other_binding['created'] = 77
        other = PayloadJournal(self.root, other_binding)
        other.ingest(self.poll, module, NOW)
        self.assertNotEqual(other.public_status()['capture_session_id'], journal.public_status()['capture_session_id'])
        other_rows = [row for path, row in lines(other.root) if row.get('capture_session_id') == other.public_status()['capture_session_id']]
        self.assertEqual(other_rows[0]['target']['pid'], 50)
        own = [row for path, row in lines(journal.root) if row.get('capture_session_id') == journal.public_status()['capture_session_id']]
        self.assertTrue(all(row['target']['pid'] == BINDING['pid'] for row in own))
        self.assertFalse(any(row.get('raw_hex') == self.payload.hex() for row in other_rows))
        journal.close()
        other.close()

    def test_session_quota_exact_boundary_and_roll_total(self):
        probe = PayloadJournal(self.root, BINDING)
        self.assertEqual(probe.max_session_bytes, MAX_SESSION_BYTES)
        self.assertEqual(MAX_SESSION_BYTES, 256 * 1024 * 1024)
        self.assertEqual(probe.public_status()['bytes_written'], 0)
        self.assertFalse(probe.public_status()['quota_exceeded'])
        probe.ingest(deepcopy(self.poll), self.module, NOW)
        size = probe.public_status()['bytes_written']
        probe_session = probe.public_status()['capture_session_id']
        probe_files = sorted(probe.root.rglob('%s-seg-*.jsonl' % probe_session))
        self.assertEqual(len(probe_files), 1)
        self.assertEqual(probe_files[0].stat().st_size, size)
        kept = probe_files[0].read_bytes()
        probe.close()

        tight = PayloadJournal(self.root, BINDING, max_session_bytes=size)
        try:
            tight.ingest(deepcopy(self.poll), self.module, NOW)
            self.assertEqual(tight.public_status()['bytes_written'], size)
            self.assertFalse(tight.public_status()['quota_exceeded'])
            session = tight.public_status()['capture_session_id']
            before = {path: path.read_bytes() for path in tight.root.rglob('%s-seg-*.jsonl' % session)}
            failures = tight.public_status()['write_failures']
            tight.ingest(deepcopy(self.poll), self.module, NOW)
            status = tight.public_status()
            self.assertTrue(status['quota_exceeded'])
            self.assertEqual(status['bytes_written'], size)
            self.assertEqual(status['last_write_error'], 'session_quota')
            self.assertEqual(status['write_error'], 'session_quota')
            self.assertGreater(status['write_failures'], failures)
            self.assertGreaterEqual(status['dropped_records'], 1)
            after = {path: path.read_bytes() for path in tight.root.rglob('%s-seg-*.jsonl' % session)}
            self.assertEqual(after, before)
            unknown = {
                'status': 'unknown', 'reason': 'core_anchor', 'events': [],
                'gaps': [{'sample': 9, 'reason': 'core_anchor'}], 'drop_count': 0, 'sample': 9,
                'binding': self.poll['binding'], 'generation': self.poll['generation'],
                'module': self.poll['module'], 'capture_session_is_match_id': False,
            }
            failures = status['write_failures']
            tight.ingest(unknown, self.module, NOW)
            self.assertEqual(tight.public_status()['write_failures'], failures)
            self.assertEqual(tight.public_status()['bytes_written'], size)
            still = {path: path.read_bytes() for path in tight.root.rglob('%s-seg-*.jsonl' % session)}
            self.assertEqual(still, before)
            self.assertEqual(probe_files[0].read_bytes(), kept)
        finally:
            tight.close()
            self.assertTrue(tight.public_status()['journal_closed'])

        rolled = PayloadJournal(self.root, BINDING, max_segment_bytes=size, max_session_bytes=size * 2)
        try:
            rolled.ingest(deepcopy(self.poll), self.module, NOW)
            session = rolled.public_status()['capture_session_id']
            first = next(rolled.root.rglob('%s-seg-0001.jsonl' % session))
            first_bytes = first.read_bytes()
            self.assertEqual(len(first_bytes), size)
            rolled.ingest(deepcopy(self.poll), self.module, NOW)
            files = sorted(rolled.root.rglob('%s-seg-*.jsonl' % session))
            self.assertEqual(len(files), 2)
            self.assertEqual(first.read_bytes(), first_bytes)
            total = sum(path.stat().st_size for path in files)
            self.assertEqual(rolled.public_status()['bytes_written'], size * 2)
            self.assertEqual(total, size * 2)
            self.assertFalse(rolled.public_status()['quota_exceeded'])
            snapshot = {path: path.read_bytes() for path in files}
            rolled.ingest(deepcopy(self.poll), self.module, NOW)
            self.assertTrue(rolled.public_status()['quota_exceeded'])
            self.assertEqual(rolled.public_status()['bytes_written'], size * 2)
            self.assertEqual(rolled.public_status()['last_write_error'], 'session_quota')
            self.assertEqual({path: path.read_bytes() for path in files}, snapshot)
            self.assertEqual(probe_files[0].read_bytes(), kept)
        finally:
            rolled.close()

    def test_zero_quota_does_not_fall_back_to_default_or_create_a_file(self):
        journal = PayloadJournal(self.root, BINDING, max_session_bytes=0)
        try:
            journal.ingest(self.poll, self.module, NOW)
            status = journal.public_status()
            self.assertTrue(status['quota_exceeded'])
            self.assertEqual(status['bytes_written'], 0)
            self.assertEqual(list(journal.root.rglob('*.jsonl')), [])
        finally:
            journal.close()

    def test_failed_physical_writes_keep_their_reservation_across_recovery(self):
        probe = PayloadJournal(self.root, BINDING)
        probe.ingest(self.poll, self.module, NOW)
        size = probe.public_status()['bytes_written']
        probe.close()
        original_open = Path.open
        for partial in (False, True):
            journal = PayloadJournal(self.root, BINDING, max_session_bytes=size)
            class WriteThenFail:
                def __init__(self, raw): self.raw = raw
                def write(self, text):
                    self.raw.write(text[:1] if partial else text)
                    self.raw.flush()
                    raise OSError('after physical write')
                def flush(self): self.raw.flush()
                def close(self): self.raw.close()
            def wrapped(path, mode='r', *args, **kwargs):
                handle = original_open(path, mode, *args, **kwargs)
                return WriteThenFail(handle) if 'a' in mode else handle
            try:
                with self.subTest(partial=partial), patch.object(Path, 'open', wrapped):
                    journal.ingest(self.poll, self.module, NOW)
                status = journal.public_status()
                self.assertEqual(status['bytes_written'], size)
                self.assertEqual(status['first_write_error'], 'after physical write')
                self.assertTrue(status['quota_exceeded'])
                self.assertGreaterEqual(status['dropped_records'], 1)
                pattern = status['capture_session_id'] + '-seg-*.jsonl'
                files = list(journal.root.rglob(pattern))
                actual = sum(path.stat().st_size for path in files)
                self.assertLessEqual(actual, size)
                self.assertEqual(actual, 1 if partial else size)
                before = {path: path.read_bytes() for path in files}
                journal.ingest(self.poll, self.module, NOW)
                self.assertEqual({path: path.read_bytes() for path in files}, before)
            finally:
                journal.close()


class ReviewRegressionTests(unittest.TestCase):
    def build_obs(self, payload=b'core-unverified'):
        return ObserverTests().build([payload])

    def test_core_anchor_and_vtable_are_read_around_the_poll(self):
        memory, module, obs = self.build_obs(b'\x10\x02verified')
        result = obs.poll()
        self.assertEqual(result['event_count'], 1)
        anchor_reads = [1 for addr, size in memory.calls if addr == CORE_ANCHOR and size == 4]
        vtable_reads = [1 for addr, size in memory.calls if addr == BINDING['core'] and size == 4]
        self.assertGreaterEqual(len(anchor_reads), 2)
        self.assertGreaterEqual(len(vtable_reads), 2)
        text = ' '.join(result['limitations'])
        self.assertIn('failures', text)
        self.assertIn('thread', text)

        memory, module, obs = self.build_obs()
        del memory.regions[CORE_ANCHOR]
        del memory.regions[BINDING['core']]
        refused = obs.poll()
        self.assertEqual(refused['events'], [])
        self.assertEqual(refused['status'], 'unknown')
        self.assertTrue(refused['gaps'])
        self.assertEqual(refused['gaps'][0]['reason'], 'core_anchor')
        self.assertTrue(any(addr == CORE_ANCHOR and size == 4 for addr, size in memory.calls))

        memory, module, obs = self.build_obs()
        memory.regions[CORE_ANCHOR][:] = struct.pack('<I', BINDING['core'] + 4)
        wrong = obs.poll()
        self.assertEqual(wrong['events'], [])
        self.assertEqual(wrong['gaps'][0]['reason'], 'core_anchor')

        memory, module, obs = self.build_obs()
        memory.regions[BINDING['core']][:] = struct.pack('<I', 0x11111111)
        wrong = obs.poll()
        self.assertEqual(wrong['events'], [])
        self.assertEqual(wrong['gaps'][0]['reason'], 'core_vtable')
        self.assertNotEqual(0x11111111, CORE_VTABLE)

        memory, module, obs = self.build_obs(b'\x77post')
        memory.script.append((nth_read(BINDING['core'], 4, 2), struct.pack('<I', 0)))
        late = obs.poll()
        self.assertEqual(late['events'], [])
        self.assertEqual(late['status'], 'unknown')
        self.assertIn('core_vtable', [gap['reason'] for gap in late['gaps']])

    def test_unknown_without_gaps_is_still_recorded(self):
        memory, module, obs = self.build_obs(b'\x01bind')
        memory.identity['creation_filetime'] += 1
        result = obs.poll()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['reason'], 'binding')
        self.assertTrue(result['gaps'])
        self.assertEqual(memory.calls, [])
        root = Path(tempfile.mkdtemp())
        journal = PayloadJournal(root, BINDING)
        try:
            journal.ingest(result, module, NOW)
            self.assertGreaterEqual(journal.public_status()['gaps'], 1)
            self.assertIsNone(journal.public_status()['last_write_error'])
            self.assertTrue(any(row['kind'] == 'network_payload_gap' and row['reason'] == 'binding' for _, row in lines(journal.root)))
            bare = {
                'status': 'unknown', 'reason': 'clock', 'events': [], 'gaps': [],
                'drop_count': 0, 'sample': 2, 'binding': result['binding'],
                'generation': result['generation'], 'module': result['module'],
            }
            journal.ingest(bare, module, NOW)
            self.assertTrue(any(row['reason'] == 'clock' for _, row in lines(journal.root)))
            journal.ingest(bare, module, NOW)
            clock_rows = [row for _, row in lines(journal.root) if row.get('reason') == 'clock']
            self.assertEqual(len(clock_rows), 1)
            self.assertIsNone(journal.public_status()['last_write_error'])
        finally:
            journal.close()

    def test_first_write_failure_is_not_cleared_by_the_second_event(self):
        memory, module, first = ObserverTests().build([b'first'])
        _, _, second = ObserverTests().build([b'second'])
        # One poll with both events, sharing the first observer's binding and generation.
        primary = first.poll()
        extra = second.poll()
        primary['events'].append(extra['events'][0])
        primary['events'][1]['binding'] = primary['binding']
        primary['events'][1]['generation'] = primary['generation']
        primary['events'][1]['module'] = primary['module']
        primary['events'][1]['fake'] = primary['module']['fake']
        root = Path(tempfile.mkdtemp())
        journal = PayloadJournal(root, BINDING)
        real_open = Path.open
        state = {'raised': False}

        class Once:
            def __init__(self, raw):
                self.raw = raw
            def write(self, data):
                if not state['raised']:
                    state['raised'] = True
                    raise OSError('injected')
                return self.raw.write(data)
            def flush(self):
                self.raw.flush()
            def close(self):
                self.raw.close()

        def wrapped(path, mode='r', *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            if 'a' in str(mode) and str(path).endswith('.jsonl'):
                return Once(handle)
            return handle

        try:
            with patch.object(Path, 'open', wrapped):
                journal.ingest(primary, module, NOW)
            status = journal.public_status()
            body = ''.join(path.read_text(encoding='utf-8') for path in journal.root.rglob('*.jsonl'))
            self.assertIn(b'second'.hex(), body)
            self.assertNotIn(b'first'.hex(), body)
            self.assertGreaterEqual(status['dropped_records'], 1)
            self.assertGreaterEqual(status['drops'], 1)
            self.assertGreaterEqual(status['write_failures'], 1)
            self.assertIsNotNone(status['last_write_error'])
            self.assertIsNotNone(status['write_error'])
            quiet = dict(primary)
            quiet['events'] = []
            quiet['gaps'] = []
            quiet['status'] = 'ok'
            quiet['drop_count'] = 0
            journal.ingest(quiet, module, NOW)
            self.assertEqual(journal.public_status()['last_write_error'], status['last_write_error'])
            self.assertGreaterEqual(journal.public_status()['dropped_records'], 1)
        finally:
            journal.close()

    def test_short_write_seals_the_segment_without_rewriting_it(self):
        memory, module, obs = self.build_obs(b'short-write-payload')
        poll = obs.poll()
        root = Path(tempfile.mkdtemp())
        journal = PayloadJournal(root, BINDING)
        real_open = Path.open

        class Short:
            def __init__(self, raw):
                self.raw = raw
            def write(self, data):
                self.raw.write(data[:1])
                self.raw.flush()
                return 1
            def flush(self):
                self.raw.flush()
            def close(self):
                self.raw.close()

        def wrapped(path, mode='r', *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            if 'a' in str(mode) and str(path).endswith('.jsonl'):
                return Short(handle)
            return handle

        try:
            with patch.object(Path, 'open', wrapped):
                journal.ingest(poll, module, NOW)
            files = sorted(journal.root.rglob('*.jsonl'))
            self.assertTrue(files)
            first = files[0].read_bytes()
            self.assertEqual(len(first), 1)
            again = files[0].read_bytes()
            self.assertEqual(again, first)
            self.assertNotIn(b'short-write-payload'.hex().encode('ascii'), b''.join(path.read_bytes() for path in files))
            self.assertIsNotNone(journal.public_status()['last_write_error'])
            self.assertGreaterEqual(journal.public_status()['dropped_records'], 1)
        finally:
            journal.close()

    def test_old_poll_is_not_relabeled_onto_a_new_binding_or_generation(self):
        memory, module, obs = self.build_obs(b'old-instance')
        poll = obs.poll()
        root = Path(tempfile.mkdtemp())
        original = PayloadJournal(root, BINDING)
        other_binding = dict(BINDING)
        other_binding['pid'] = 50
        other_binding['created'] = 77
        other = PayloadJournal(root, other_binding)
        try:
            original.ingest(poll, module, NOW)
            other.ingest(poll, module, NOW)
            other_rows = [row for _, row in lines(other.root) if row.get('capture_session_id') == other.public_status()['capture_session_id']]
            self.assertTrue(other_rows)
            self.assertTrue(all(row['kind'] == 'network_payload_gap' for row in other_rows))
            self.assertFalse(any(row.get('raw_hex') == b'old-instance'.hex() for row in other_rows))
            self.assertTrue(all(row.get('capture_session_is_match_id') is False for row in other_rows))
            own = [row for _, row in lines(original.root) if row.get('kind') == 'network_payload_observation']
            self.assertEqual(own[0]['target']['pid'], 1096)
            self.assertEqual(own[0]['generation'], poll['generation'])
            fresh = observer(memory, module)
            moved = fresh.poll()
            original.ingest(moved, module, NOW)
            generations = [row.get('generation') for _, row in lines(original.root) if row.get('kind') == 'network_payload_observation']
            self.assertEqual(generations, [poll['generation']])
            self.assertNotEqual(moved['generation'], poll['generation'])
            self.assertTrue(any(row.get('reason') == 'generation' for _, row in lines(original.root)))
            switched = deepcopy(poll)
            switched['module'] = dict(switched['module'])
            switched['module']['base'] = switched['module']['base'] + 0x1000
            switched['events'] = []
            newer = PayloadJournal(root, BINDING)
            try:
                newer.ingest(switched, module, NOW)
                self.assertTrue(any(row.get('reason') == 'module' for _, row in lines(newer.root) if row.get('capture_session_id') == newer.public_status()['capture_session_id']))
                self.assertFalse(any(row.get('kind') == 'network_payload_observation' for _, row in lines(newer.root) if row.get('capture_session_id') == newer.public_status()['capture_session_id']))
                fake_poll = deepcopy(poll)
                fake_poll['module'] = dict(fake_poll['module'])
                fake_poll['module']['fake'] = False
                fake_poll['events'] = [dict(fake_poll['events'][0], fake=False, module=fake_poll['module'])]
                claimed = PayloadJournal(root, BINDING)
                try:
                    claimed.ingest(fake_poll, module, NOW)
                    claimed_rows = [row for _, row in lines(claimed.root) if row.get('capture_session_id') == claimed.public_status()['capture_session_id']]
                    self.assertTrue(any(row.get('reason') == 'fake' for row in claimed_rows))
                    self.assertFalse(any(row.get('fake') is False and row.get('raw_hex') for row in claimed_rows))
                finally:
                    claimed.close()
            finally:
                newer.close()
        finally:
            original.close()
            other.close()

    def test_budget_is_checked_after_the_last_read(self):
        payload = b'\x42tail'
        memory, module, obs = self.build_obs(payload)
        obs.poll()
        reads = len(memory.calls)
        clock = {'t': 0.0}
        memory, module, _obs = self.build_obs(payload)
        original = memory.read

        def read(address, size):
            data = original(address, size)
            if len(memory.calls) >= reads:
                clock['t'] = 7.0
            return data

        memory.read = read
        watched = observer(memory, module, clock=clock)
        result = watched.poll()
        self.assertGreaterEqual(result['elapsed_s'], 7)
        self.assertTrue(result['budget_gap'])
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(any(gap['reason'] == 'budget' for gap in result['gaps']))
        self.assertLessEqual(len(result['gaps']), 16)
        self.assertEqual(result['events'][0]['raw_hex'], payload.hex())


if __name__ == '__main__':
    unittest.main()
