"""Deterministic lifecycle tests with fake memory and temporary journals."""
import hashlib
import json
import struct
import tempfile
import threading
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import network_payload_worker as worker
from network_payloads import CORE_ANCHOR, CORE_VTABLE, DIRECTORY_NAME, NetworkPayloadObserver, PayloadJournal
from test_network_payloads import BASE, ARRAY, PAYLOAD, BINDING, FakeMemory, entry_bytes, module_for, pe_image, put_head


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
        self.tick = 100.0
        self.calls, self.readers, self.captures = [], [], []
        self.image = pe_image()
        put_head(self.image, 0, 0, 0)
        self.module = module_for(self.image)

    def tearDown(self):
        for capture in self.captures:
            capture.close()
        self.temp.cleanup()

    def payload(self, binding=None):
        binding = binding or BINDING
        identity = {'pid': binding['pid'], 'path': binding['image'], 'creation_filetime': binding['created']}
        return {'phase': 'waiting_for_player', 'fresh': False, 'error': None,
                'source_id': binding['source_id'], 'identity': identity, 'core_address': hex(binding['core']),
                'state': {'identity': dict(identity, created_utc=self.now.isoformat()),
                          'build_sha256': binding['build'], 'core_address': hex(binding['core']),
                          'capture_end': self.now.isoformat(),
                          'consistency': {'root_headers_and_clock_unchanged': True}}}

    def memory(self, binding):
        calls = self.calls
        image = bytearray(self.image)
        regions = {BASE: image, CORE_ANCHOR: struct.pack('<I', binding['core']),
                   binding['core']: struct.pack('<I', CORE_VTABLE)}
        identity = {'pid': binding['pid'], 'path': binding['image'], 'creation_filetime': binding['created']}
        inner = FakeMemory(regions, identity)

        class Reader:
            h = 1
            calls = bytes = read_failures = 0
            closed = False

            def __init__(self):
                self.identity, self.inner = identity, inner

            def read(self, address, size):
                self.calls += 1
                data = inner.read(address, size)
                if data is None:
                    self.read_failures += 1
                else:
                    self.bytes += len(data)
                return data

            def close(self):
                if not self.closed:
                    calls.append(('close', binding['created'], binding['core']))
                self.closed, self.h = True, None

        reader = Reader()
        calls.append(('open', binding['created'], binding['core']))
        self.readers.append(reader)
        return reader

    def capture(self, **kwargs):
        options = dict(memory_factory=self.memory, module_resolver=lambda memory: deepcopy(self.module),
                       observer_factory=lambda memory, binding, module: NetworkPayloadObserver(
                           memory, binding, module, monotonic=lambda: self.tick, clock=lambda: self.now),
                       clock=lambda: self.now, monotonic=lambda: self.tick)
        options.update(kwargs)
        capture = worker.PayloadCapture(self.root, **options)
        self.captures.append(capture)
        return capture

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
        self.tick += seconds

    def test_same_binding_is_reused_and_creation_or_core_change_closes_before_open(self):
        capture = self.capture()
        payload = self.payload()
        capture.update(payload); capture.step()
        first = capture.public_status()['journal']['capture_session_id']
        for _ in range(3):
            capture.update(payload); capture.step()
        self.assertEqual(len(self.readers), 1)
        self.assertEqual(capture.public_status()['journal']['capture_session_id'], first)
        binding = dict(BINDING, created=BINDING['created'] + 1)
        capture.update(self.payload(binding)); capture.step()
        self.assertEqual(self.calls[1][0], 'close')
        self.assertEqual(self.calls[2][0], 'open')
        second = capture.public_status()['journal']['capture_session_id']
        self.assertNotEqual(first, second)
        binding['core'] += 0x1000
        capture.update(self.payload(binding)); capture.step()
        self.assertEqual([item[0] for item in self.calls], ['open', 'close', 'open', 'close', 'open'])
        self.assertFalse(capture.public_status()['action_training_eligible'])
        self.assertTrue(capture.public_status()['fake'])

    def test_expiry_without_another_update_releases_and_recovery_uses_new_session(self):
        capture = self.capture()
        capture.update(self.payload()); capture.step()
        first = capture.public_status()['journal']['capture_session_id']
        self.advance(4.01)
        capture.step()
        self.assertTrue(self.readers[0].closed)
        self.assertEqual(capture.public_status()['error'], 'stale')
        capture.update(self.payload()); capture.step()
        self.assertNotEqual(first, capture.public_status()['journal']['capture_session_id'])
        capture.update(None); capture.step()
        self.assertTrue(self.readers[-1].closed)
        self.assertIsNone(capture.public_status()['binding'])

    def test_cleared_queue_stale_cursor_keeps_same_worker_and_journal(self):
        put_head(self.image, ARRAY, 0, 2)
        capture = self.capture()
        for _ in range(8):
            capture.update(self.payload()); capture.step()
        status = capture.public_status()
        self.assertEqual(status['phase'], 'sampling')
        self.assertEqual(status['errors'], 0)
        self.assertEqual(status['unknown_polls'], 0)
        self.assertEqual(len(self.readers), 1)
        self.assertFalse(self.readers[0].closed)
        self.assertEqual(status['journal']['samples'], 8)

    def test_invalid_or_old_snapshots_never_open_a_reader(self):
        valid = self.payload()
        invalid = [None, dict(valid, phase='multiple'), dict(valid, error='failed'),
                   dict(valid, identity=None), dict(valid, phase='live', fresh=False)]
        for mutate in (
            lambda p: p['identity'].update(pid=5),
            lambda p: p['state'].update(build_sha256='0' * 64),
            lambda p: p['state']['consistency'].update(root_headers_and_clock_unchanged=False),
            lambda p: p['state'].update(capture_end=(self.now - timedelta(seconds=5)).isoformat()),
            lambda p: p['state'].update(capture_end=(self.now + timedelta(seconds=2)).isoformat()),
            lambda p: p.update(core_address='0x1'),
            lambda p: p['state'].update(core_address='0x100000000'),
        ):
            data = deepcopy(valid); mutate(data); invalid.append(data)
        capture = self.capture()
        for data in invalid:
            capture.update(data); capture.step()
        self.assertEqual(self.readers, [])
        self.assertEqual(list(self.root.rglob('*.jsonl')), [])

    def test_unknown_core_stops_after_three_polls_and_backs_off(self):
        capture = self.capture()
        capture.update(self.payload()); capture.step()
        self.readers[0].inner.regions[CORE_ANCHOR][:] = struct.pack('<I', BINDING['core'] + 1)
        for _ in range(3):
            capture.step()
        status = capture.public_status()
        self.assertEqual(status['phase'], 'backoff')
        self.assertEqual(status['unknown_polls'], 3)
        self.assertTrue(self.readers[0].closed)
        for _ in range(10):
            capture.update(self.payload()); capture.step()
        self.assertEqual(len(self.readers), 1)
        self.advance(5)
        capture.update(self.payload()); capture.step()
        self.assertEqual(len(self.readers), 2)
        self.assertEqual(capture.public_status()['phase'], 'sampling')

    def test_module_failure_closes_handle_and_changed_binding_retries_immediately(self):
        capture = self.capture(module_resolver=lambda memory: {'status': 'unknown'})
        capture.update(self.payload()); capture.step()
        self.assertTrue(self.readers[0].closed)
        for _ in range(5):
            capture.step()
        self.assertEqual(len(self.readers), 1)
        capture.update(self.payload(dict(BINDING, core=BINDING['core'] + 0x1000))); capture.step()
        self.assertEqual(len(self.readers), 2)
        self.assertTrue(self.readers[1].closed)

    def test_revocation_during_poll_discards_bytes_and_closes_the_old_binding(self):
        holder = {}

        def observer(memory, binding, module):
            actual = NetworkPayloadObserver(memory, binding, module, monotonic=lambda: self.tick)
            class Revoke:
                def poll(self):
                    holder['capture'].update(None)
                    return actual.poll()
            return Revoke()

        capture = holder['capture'] = self.capture(observer_factory=observer)
        capture.update(self.payload()); capture.step()
        self.assertTrue(self.readers[0].closed)
        self.assertEqual(capture.public_status()['discarded_polls'], 1)
        rows = [json.loads(line) for path in self.root.rglob('*.jsonl') for line in path.read_text().splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row['kind'] == 'network_payload_gap' for row in rows))
        self.assertTrue(all(row['fake'] for row in rows))

    def test_raw_payload_is_saved_once_with_hash_and_unknown_action_labels(self):
        capture = self.capture()
        capture.update(self.payload()); capture.step()
        memory = self.readers[0].inner
        raw = b'\x10\x00\xff\x7f'
        put_head(memory.regions[BASE], ARRAY, 1, 0)
        memory.regions[ARRAY] = bytearray(entry_bytes(42, PAYLOAD, len(raw)))
        memory.regions[PAYLOAD] = bytearray(raw)
        capture.step(); capture.step()
        rows = [json.loads(line) for path in self.root.rglob('*.jsonl') for line in path.read_text().splitlines()]
        saved = [row for row in rows if row['kind'] == 'network_payload_observation']
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['raw_hex'], raw.hex())
        self.assertEqual(saved[0]['raw_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertTrue(saved[0]['fake'])
        self.assertIsNone(saved[0]['decoded_action'])
        self.assertIsNone(saved[0]['actor_force_id'])
        self.assertFalse(saved[0]['action_training_eligible'])
        self.assertNotIn(raw.hex(), json.dumps(capture.public_status()))

    def test_poll_exception_is_visible_and_closes_only_own_reader(self):
        class Broken:
            def poll(self):
                raise RuntimeError('fake poll failed')
        capture = self.capture(observer_factory=lambda *args: Broken())
        capture.update(self.payload()); capture.step()
        self.assertTrue(self.readers[0].closed)
        self.assertIn('fake poll failed', capture.public_status()['last_error'])
        self.assertEqual(capture.public_status()['phase'], 'backoff')

    def test_write_failure_is_visible_and_stops_the_session(self):
        class BrokenJournal(PayloadJournal):
            def ingest(self, *args):
                self.write_error = self.last_write_error = 'fake disk full'
        capture = self.capture(journal_factory=BrokenJournal)
        capture.update(self.payload()); capture.step()
        self.assertTrue(self.readers[0].closed)
        self.assertIn('fake disk full', capture.public_status()['last_journal']['write_error'])
        self.assertFalse(capture.public_status()['absence_means_no_command'])

    def test_session_quota_and_directory_quota_preserve_old_files(self):
        # Unknown core creates a real gap record, too large for a one-byte budget.
        capture = self.capture(max_session_bytes=1)
        capture.update(self.payload()); capture.step()
        self.readers[0].inner.regions[CORE_ANCHOR][:] = b'\0' * 4
        capture.step()
        self.assertEqual(capture.public_status()['phase'], 'quota')
        self.assertTrue(capture.public_status()['last_journal']['quota_exceeded'])
        capture.step()
        self.assertEqual(capture.public_status()['phase'], 'quota')
        folder = self.root / DIRECTORY_NAME
        folder.mkdir(exist_ok=True)
        sentinel = folder / 'preserve.jsonl'; sentinel.write_bytes(b'x')
        other = self.capture(max_directory_bytes=1)
        opens = len(self.readers)
        other.update(self.payload()); other.step()
        self.assertEqual(other.public_status()['phase'], 'quota')
        self.assertEqual(len(self.readers), opens)
        self.assertEqual(sentinel.read_bytes(), b'x')

    def test_directory_scan_rejects_links_depth_and_excess_entries(self):
        folder = self.root / DIRECTORY_NAME; folder.mkdir()
        (folder / 'one').write_bytes(b'1')
        (folder / 'two').write_bytes(b'22')
        self.assertEqual(worker.directory_bytes(folder), 3)
        with self.assertRaisesRegex(ValueError, 'entry limit'):
            worker.directory_bytes(folder, entry_limit=1)
        deep = folder
        for _ in range(worker.MAX_DIRECTORY_DEPTH + 1):
            deep = deep / 'deep'; deep.mkdir()
        with self.assertRaisesRegex(ValueError, 'depth limit'):
            worker.directory_bytes(folder)
        for path in reversed(list(folder.rglob('deep'))):
            path.rmdir()
        try:
            # Relative target is valid on both Windows and Wine's host FS.
            (folder / 'link').symlink_to('one')
        except OSError:
            self.skipTest('symbolic links are unavailable on this platform')
        if not (folder / 'link').exists():
            self.skipTest('OS returned success without creating a symbolic link')
        capture = self.capture()
        capture.update(self.payload()); capture.step()
        self.assertEqual(capture.public_status()['phase'], 'backoff')
        self.assertIn('quota_unknown', capture.public_status()['error'])
        self.assertEqual(self.readers, [])

    def test_journal_root_alias_is_rejected_before_opening_the_game(self):
        target = self.root / 'target'; target.mkdir()
        try:
            (self.root / DIRECTORY_NAME).symlink_to('target', target_is_directory=True)
        except OSError:
            self.skipTest('symbolic links are unavailable on this platform')
        if not (self.root / DIRECTORY_NAME).exists():
            self.skipTest('OS returned success without creating a symbolic link')
        capture = self.capture()
        capture.update(self.payload()); capture.step()
        self.assertIn('quota_unknown', capture.public_status()['error'])
        self.assertEqual(self.readers, [])

    def test_start_stop_are_idempotent_and_do_not_launch_a_game(self):
        capture = self.capture()
        capture.start()
        thread = capture._thread
        capture.start()
        self.assertIs(capture._thread, thread)
        capture.close(); capture.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.readers, [])
        self.assertEqual(capture.public_status()['phase'], 'stopped')

    def test_close_never_closes_a_handle_still_in_use_by_worker_thread(self):
        entered, release = threading.Event(), threading.Event()
        def observe(memory, binding, module):
            put_head(memory.inner.regions[BASE], ARRAY, 1, 0)
            memory.inner.regions[ARRAY] = bytearray(entry_bytes(42, PAYLOAD, 4))
            memory.inner.regions[PAYLOAD] = bytearray(b'raw!')
            actual = NetworkPayloadObserver(memory, binding, module, monotonic=lambda: self.tick)
            class Blocking:
                def poll(self):
                    entered.set()
                    release.wait(5)
                    return actual.poll()
            return Blocking()
        capture = self.capture(observer_factory=observe)
        capture.update(self.payload()); capture.start()
        try:
            self.assertTrue(entered.wait(1))
            capture.close()
            self.assertTrue(capture.public_status()['shutdown_pending'])
            self.assertFalse(self.readers[0].closed)
        finally:
            release.set()
            capture._thread.join(2)
        self.assertTrue(self.readers[0].closed)
        self.assertFalse(capture.public_status()['shutdown_pending'])
        self.assertEqual(capture.public_status()['discarded_polls'], 1)
        rows = [json.loads(line) for path in self.root.rglob('*.jsonl') for line in path.read_text().splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row['kind'] == 'network_payload_gap' for row in rows))


class ReaderTests(unittest.TestCase):
    def test_failed_identity_or_executable_validation_releases_only_its_handle(self):
        for cause in ('identity', 'file', 'hash'):
            closed = []
            class Api:
                def open_process(self, pid): return 123
                def query_path(self, handle): return BINDING['image']
                def process_times(self, handle): return (BINDING['created'] + (cause == 'identity'), 'fake')
                def close_handle(self, handle): closed.append(handle)
            def read_file(path):
                if cause == 'file': raise OSError('fake file error')
                return b'not a game'
            with self.subTest(cause=cause), self.assertRaises((ValueError, OSError)):
                worker.ReadOnlyMemory(BINDING, api=Api(), read_file=read_file)
            self.assertEqual(closed, [123])

    def test_reader_rejects_large_short_and_closed_reads_without_a_failure_list(self):
        closed, reads = [], []
        class Api:
            def open_process(self, pid): return 123
            def query_path(self, handle): return BINDING['image']
            def process_times(self, handle): return BINDING['created'], 'fake'
            def close_handle(self, handle): closed.append(handle)
        def read(handle, address, size):
            reads.append((handle, address, size))
            return b'x'
        with patch.object(worker, 'SANPK_BUILD', hashlib.sha256(b'fake exe').hexdigest()):
            memory = worker.ReadOnlyMemory(BINDING, api=Api(), read_file=lambda path: b'fake exe', read_process=read)
        self.assertIsNone(memory.read(0, 1))
        self.assertIsNone(memory.read(0x10000, 8193))
        self.assertIsNone(memory.read(0x10000, 2))
        self.assertEqual(len(reads), 1)
        self.assertEqual(memory.read_failures, 3)
        self.assertFalse(hasattr(memory, 'failures'))
        memory.close(); memory.close()
        self.assertEqual(closed, [123])
        self.assertIsNone(memory.read(0x10000, 1))
        self.assertEqual(len(reads), 1)


if __name__ == '__main__':
    unittest.main()
