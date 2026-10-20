"""Bounded read-only KOEINM queue sample and append-only payload journal.

This is not a complete command stream. GetCmd, EndSync, and every other
target function stay uncalled. Root owns the process handle, the thread,
and Memory.read. A capture session is not a match id.
"""
import hashlib
import json
import struct
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import target_codepage

SANPK_BUILD = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
KOEINM_SHA = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
KOEINM_RECONNECT_R1_SHA = '25e9e54d7ec11a64287130fa614c1ab80e041fa0864a406ae76de030d512ee83'

KOEINM_RECONNECT_R2_SHA = '28476038d67d2f330860d88b3dd0be53594354107cfd26ecb36ddf8512d111d8'

def is_supported_network_sha(value):
    # All audited builds retain the queue/member layout; record the actual SHA.
    return type(value) is str and value in (KOEINM_SHA, KOEINM_RECONNECT_R1_SHA, KOEINM_RECONNECT_R2_SHA)

SCHEMA = 'native-payload-observation-1'
CONTEXT_RVA = 0x12170
HEAD_OFFSET = 0x84b0
HEAD_SIZE = 20
ENTRY_SIZE = 12
CONTEXT_END_RVA = CONTEXT_RVA + HEAD_OFFSET + HEAD_SIZE
CORE_ANCHOR = 0x53bb30
CORE_VTABLE = 0x5053c0
USER_LOW = target_codepage.USER_LOW
USER_HIGH = target_codepage.USER_HIGH
MACHINE_I386 = target_codepage.MACHINE_I386
PE32 = target_codepage.PE32
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_QUEUE_ENTRIES = 256
MAX_PAYLOAD = 4096
MAX_SAMPLE_PAYLOAD = 64 * 1024
MAX_SAMPLE_EVENTS = 32
MAX_GAPS = 16
MAX_CACHE_KEYS = 512
BUDGET_S = 0.005
MAX_RECORD_BYTES = 64 * 1024
MAX_SEGMENT_BYTES = 4 * 1024 * 1024
MAX_SESSION_BYTES = 256 * 1024 * 1024
DIRECTORY_NAME = 'native-payload-observations'
LIMITATIONS = (
    'aba_reuse_between_polls_is_not_observable',
    'not_a_complete_command_stream',
    'empty_queue_does_not_prove_no_command',
    'local_direct_dispatch_is_not_observed',
    'payload_bytes_are_not_decoded',
    'external_poller_must_own_the_memory_handle_and_clear_its_failures_list',
    'this_component_does_not_start_a_thread',
    'soft_time_budget_is_not_a_hard_realtime_guarantee',
)


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    raise TypeError('now must be a datetime')


def _basename(path):
    if type(path) is not str or not path:
        return ''
    slash = max(path.rfind('\\'), path.rfind('/'))
    name = path[slash + 1:] if slash >= 0 else path
    return name.lower()


def _in_range(address, size):
    if type(address) is not int or type(size) is not int or isinstance(address, bool) or isinstance(size, bool):
        return False
    if address < USER_LOW or address >= USER_HIGH or size <= 0:
        return False
    if size > USER_HIGH - address:
        return False
    return True


def _binding_fields(binding):
    if not isinstance(binding, dict):
        return None
    pid = binding.get('pid')
    created = binding.get('created')
    image = binding.get('image')
    core = binding.get('core')
    build = binding.get('build')
    source = binding.get('source_id')
    if type(pid) is not int or isinstance(pid, bool) or pid <= 0:
        return None
    if type(created) is not int or isinstance(created, bool) or created <= 0:
        return None
    if type(image) is not str or not image:
        return None
    if type(core) is not int or isinstance(core, bool) or not USER_LOW <= core < USER_HIGH:
        return None
    if build != SANPK_BUILD:
        return None
    if type(source) is not str or not source or len(source) > 128:
        return None
    return {
        'pid': pid, 'created': created, 'image': image, 'core': core,
        'build': build, 'source_id': source,
    }


def _identity_matches(memory, binding):
    ident = getattr(memory, 'identity', None)
    if not isinstance(ident, dict):
        return False
    return (ident.get('pid') == binding['pid']
            and ident.get('creation_filetime') == binding['created']
            and ident.get('path') == binding['image'])


def _core_guard(memory, binding):
    """DWORD[0x53bb30] is the live core, and DWORD[core] is the SANPK vtable.

    memory.identity is fixed when the handle opens, so it cannot prove the
    current core. fake=True does not skip these reads.
    """
    anchor, error = _read(memory, CORE_ANCHOR, 4)
    if error or anchor is None:
        return 'core_anchor'
    core = struct.unpack('<I', anchor)[0]
    if core != binding['core']:
        return 'core_anchor'
    vtable, error = _read(memory, core, 4)
    if error or vtable is None:
        return 'core_vtable'
    if struct.unpack('<I', vtable)[0] != CORE_VTABLE:
        return 'core_vtable'
    return None


def _unknown(reason, fake):
    return {
        'status': 'unknown', 'reason': reason, 'fake': bool(fake),
        'read_only': True, 'no_target_calls': True,
    }


def _read(memory, address, size):
    if not _in_range(address, size):
        return None, 'address'
    try:
        data = memory.read(address, size)
    except Exception:
        return None, 'read_failed'
    if isinstance(data, bool) or not isinstance(data, (bytes, bytearray, memoryview)):
        return None, 'read_failed'
    raw = bytes(data)
    if len(raw) != size:
        return None, 'short_read'
    return raw, None


def _pe_fields(memory, base):
    if not _in_range(base, 0x40):
        return None, 'address'
    dos, error = _read(memory, base, 0x40)
    if error:
        return None, error
    if dos[:2] != b'MZ':
        return None, 'not_mz'
    e_lfanew = struct.unpack_from('<I', dos, 0x3c)[0]
    pe_size = 0x18 + 60
    if e_lfanew <= 0 or e_lfanew > 0x1000 or not _in_range(base + e_lfanew, pe_size):
        return None, 'not_pe'
    pe, error = _read(memory, base + e_lfanew, pe_size)
    if error:
        return None, error
    if pe[:4] != b'PE\0\0':
        return None, 'not_pe'
    machine = struct.unpack_from('<H', pe, 4)[0]
    if machine != MACHINE_I386:
        return None, 'machine'
    magic = struct.unpack_from('<H', pe, 24)[0]
    if magic != PE32:
        return None, 'pe32'
    image_size = struct.unpack_from('<I', pe, 24 + 56)[0]
    if image_size <= CONTEXT_END_RVA or image_size > USER_HIGH - base:
        return None, 'size_of_image'
    context_end = base + CONTEXT_END_RVA
    if context_end > USER_HIGH or CONTEXT_END_RVA > image_size:
        return None, 'context_range'
    return {
        'e_lfanew': e_lfanew,
        'machine': machine,
        'magic': magic,
        'size_of_image': image_size,
        'context_rva': CONTEXT_RVA,
        'context_end_rva': CONTEXT_END_RVA,
        'context_end': context_end,
        'header_hex': (dos + pe).hex(),
    }, None


def _default_read_file(path):
    file = Path(path)
    size = file.stat().st_size
    if type(size) is not int or size <= 0 or size > MAX_FILE_BYTES:
        return size
    return file.read_bytes()


def resolve_network_module(memory, enumerate_modules=None, read_file=None):
    """Return KOEINM evidence, or status unknown. Never raises.

    enumerate_modules and read_file exist so tests can inject fakes. An
    injected call is labeled fake and still has to match an audited DLL SHA.
    There is no production switch that skips the hash.
    """
    fake = enumerate_modules is not None or read_file is not None
    try:
        return _resolve(memory, enumerate_modules, read_file, fake)
    except Exception:
        return _unknown('exception', fake)


def _resolve(memory, enumerate_modules, read_file, fake):
    handle = getattr(memory, 'h', None)
    if not handle:
        return _unknown('no_handle', fake)
    if enumerate_modules is None:
        modules = target_codepage._enumerate_with_psapi(handle)
    else:
        modules = enumerate_modules(handle)
    if not isinstance(modules, list) or len(modules) > target_codepage.MAX_MODULES:
        return _unknown('enumerate_failed', fake)
    hits = []
    for item in modules:
        if not isinstance(item, tuple) or len(item) != 2:
            return _unknown('enumerate_failed', fake)
        base, path = item
        if type(base) is not int or isinstance(base, bool) or type(path) is not str:
            return _unknown('enumerate_failed', fake)
        if _basename(path) == 'koeinm.dll':
            hits.append((base, path))
    if not hits:
        return _unknown('not_found', fake)
    if len(hits) != 1:
        return _unknown('duplicate', fake)
    base, path = hits[0]
    if not _in_range(base, CONTEXT_END_RVA):
        return _unknown('context_range', fake)
    reader = read_file or _default_read_file
    try:
        blob = reader(path)
    except Exception:
        return _unknown('file_unreadable', fake)
    if type(blob) is int:
        return _unknown('file_too_large' if blob > MAX_FILE_BYTES else 'file_unreadable', fake)
    if isinstance(blob, bool) or not isinstance(blob, (bytes, bytearray, memoryview)):
        return _unknown('file_unreadable', fake)
    data = bytes(blob)
    if len(data) <= 0 or len(data) > MAX_FILE_BYTES:
        return _unknown('file_too_large', fake)
    digest = hashlib.sha256(data).hexdigest()
    if not is_supported_network_sha(digest):
        return _unknown('dll_sha', fake)
    headers, error = _pe_fields(memory, base)
    if error:
        return _unknown(error, fake)
    return {
        'status': 'ok',
        'base': base,
        'path': path,
        'sha256': digest,
        'context': base + CONTEXT_RVA,
        'fake': bool(fake),
        'headers': headers,
        'read_only': True,
        'no_target_calls': True,
    }


def _module_ok(module):
    if not isinstance(module, dict) or module.get('status') != 'ok':
        return None
    if not is_supported_network_sha(module.get('sha256')):
        return None
    base = module.get('base')
    path = module.get('path')
    headers = module.get('headers')
    if not _in_range(base, CONTEXT_END_RVA) or type(path) is not str or _basename(path) != 'koeinm.dll':
        return None
    if module.get('context') != base + CONTEXT_RVA or not isinstance(headers, dict):
        return None
    if headers.get('size_of_image') is None or headers.get('header_hex') is None:
        return None
    if headers.get('context_end_rva') != CONTEXT_END_RVA:
        return None
    token = headers.get('header_hex')
    if type(token) is not str or len(token) > 4096:
        return None
    return module


class NetworkPayloadObserver:
    """One poll, no sleep and no thread. Events from this call only."""

    def __init__(self, memory, binding, module, monotonic=None, clock=None):
        self.memory = memory
        self.binding = _binding_fields(binding)
        self.module = _module_ok(module) if self.binding else None
        self._monotonic = monotonic or time.perf_counter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._slots = {}
        self._next_slot = None
        self._samples = 0
        self._events = 0
        self._gaps = 0
        self._drops = 0
        self._fake = bool(self.module and self.module.get('fake'))
        self.generation = str(uuid.uuid4())
        if self.module is not None:
            self.module = deepcopy(self.module)

    def public_status(self):
        return {
            'samples': self._samples,
            'events': self._events,
            'gaps': self._gaps,
            'drops': self._drops,
            'cached_keys': len(self._slots),
            'coverage': 'partial',
            'completeness': 'unknown',
            'absence_means_no_command': False,
            'read_only': True,
            'no_target_calls': True,
            'fake': self._fake,
            'generation': self.generation,
            'capture_session_is_match_id': False,
        }

    def poll(self):
        self._samples += 1
        sample = self._samples
        if self.binding is None:
            return self._unknown(sample, 'unsupported_build')
        if self.module is None:
            return self._unknown(sample, 'module')
        if not _identity_matches(self.memory, self.binding):
            self._slots = {}
            return self._unknown(sample, 'binding')
        try:
            started = self._monotonic()
        except Exception:
            return self._unknown(sample, 'clock')
        walk = _Walk(self, sample, started)
        return walk.run()

    def _unknown(self, sample, reason):
        gap = {'sample': sample, 'reason': reason}
        return self._result(sample, 'unknown', reason, [], [gap], 0, True)

    def _module_evidence(self):
        module = self.module
        if not module:
            return None
        return {
            'base': module['base'], 'path': module['path'], 'sha256': module['sha256'],
            'context': module['context'], 'fake': bool(module.get('fake')),
        }

    def _result(self, sample, status, reason, events, gaps, drops, partial, budget=False, truncated=False, elapsed=None):
        if status == 'unknown' and not gaps:
            gaps = [{'sample': sample, 'reason': reason or 'unknown'}]
            partial = True
        self._events += len(events)
        self._gaps += len(gaps)
        self._drops += drops
        return {
            'status': status,
            'reason': reason,
            'binding': deepcopy(self.binding) if self.binding else None,
            'generation': self.generation,
            'capture_session_is_match_id': False,
            'module': self._module_evidence(),
            'elapsed_s': elapsed,
            'events': events,
            'gaps': gaps[:MAX_GAPS],
            'sample': sample,
            'event_count': len(events),
            'gap_count': len(gaps),
            'drop_count': drops,
            'partial': partial,
            'budget_gap': budget,
            'gaps_truncated': truncated,
            'coverage': 'partial',
            'completeness': 'unknown',
            'absence_means_no_command': False,
            'read_only': True,
            'no_target_calls': True,
            'fake': self._fake,
            'limitations': list(LIMITATIONS),
            'totals': {
                'samples': self._samples,
                'events': self._events,
                'gaps': self._gaps,
                'drops': self._drops,
            },
        }


class _Walk:
    def __init__(self, observer, sample, started):
        self.observer = observer
        self.memory = observer.memory
        self.sample = sample
        self.started = started
        self.events = []
        self.gaps = []
        self.drops = 0
        self.partial = False
        self.budget = False
        self.payload_bytes = 0
        self.header = None
        self.head = None
        self.head_values = None
        self.visited = {}
        self.stopped = False
        self.truncated = False

    def expired(self):
        try:
            return self.observer._monotonic() - self.started >= BUDGET_S
        except Exception:
            return True

    def add_gap(self, reason, **fields):
        if len(self.gaps) >= MAX_GAPS:
            self.partial = True
            self.stopped = True
            self.truncated = True
            return
        gap = {'sample': self.sample, 'reason': reason}
        gap.update(fields)
        self.gaps.append(gap)
        if len(self.gaps) >= MAX_GAPS:
            self.partial = True
            self.stopped = True
            self.truncated = True

    def run(self):
        if self.expired():
            self._budget()
            return self._finish('partial')
        if not self._guard():
            self.events = []
            return self._finish('unknown')
        token, error = self._token()
        if error:
            self.add_gap('changed_module_header' if error == 'changed_module_header' else error)
            self.observer._slots = {}
            return self._finish('unknown')
        self.header = token
        if not _identity_matches(self.memory, self.observer.binding):
            self.observer._slots = {}
            self.add_gap('binding')
            return self._finish('unknown')
        head, error = _read(self.memory, self._head_address(), HEAD_SIZE)
        if error:
            self.add_gap(error, queue='head')
            return self._finish('unknown')
        self.head = head
        try:
            array, count, read_index, alt_array, alt_count = struct.unpack('<5I', head)
        except struct.error:
            self.add_gap('queue_bounds')
            return self._finish('unknown')
        # KOEINM 0x10001180 clears/frees primary payloads and resets count,
        # but leaves read_index until StartSync (0x10003290) resets it.
        # The alternate queue may also be swapped in before that reset.
        # Bound each scalar independently; a stale read cursor is not an
        # entry count and must never authorize reading freed/outside slots.
        if (count > MAX_QUEUE_ENTRIES or alt_count > MAX_QUEUE_ENTRIES
                or read_index > MAX_QUEUE_ENTRIES):
            self.add_gap('queue_bounds')
            return self._finish('unknown')
        self.head_values = (array, count, read_index, alt_array, alt_count)
        plan = []
        for queue, pointer, size in (('primary', array, count), ('alternate', alt_array, alt_count)):
            if size == 0:
                continue
            span = size * ENTRY_SIZE
            if not _in_range(pointer, span):
                self.add_gap('address', queue=queue)
                continue
            for index in range(size):
                plan.append((queue, pointer, size, index))
        # A soft-budget poll must resume after its previous work. Restarting
        # at primary[0] on every call can starve later players/alternate data.
        slots = [(q,p,i) for q,p,_,i in plan]
        if self.observer._next_slot in slots:
            start = slots.index(self.observer._next_slot)
            plan = plan[start:] + plan[:start]
        if not plan:
            self.observer._next_slot = None
        for ordinal, item in enumerate(plan):
            if self.stopped:
                self.drops += len(plan) - ordinal
                break
            if self.expired():
                self.drops += len(plan) - ordinal
                self._budget()
                q,p,_,i=item;self.observer._next_slot=(q,p,i)
                break
            self._entry(item)
            q,p,_,i=item
            next_item = plan[(ordinal+1) % len(plan)] if (q,p,i) in self.visited else item
            q,p,_,i=next_item;self.observer._next_slot=(q,p,i)
            if self.expired():
                self.drops += len(plan) - ordinal - 1
                self._budget()
                self.stopped = True
                break
        if not self._guard():
            self.events = []
            self.observer._slots = {}
            return self._finish('unknown')
        if self.expired():
            self._budget()
        self._commit_slots(plan)
        status = 'partial' if self.partial or self.budget else 'ok'
        return self._finish(status)

    def _guard(self):
        if not _identity_matches(self.memory, self.observer.binding):
            self.add_gap('binding')
            self.observer._slots = {}
            return False
        error = _core_guard(self.memory, self.observer.binding)
        if error:
            self.add_gap(error)
            self.observer._slots = {}
            return False
        return True

    def _head_address(self):
        return self.observer.module['context'] + HEAD_OFFSET

    def _token(self):
        base = self.observer.module['base']
        headers = self.observer.module['headers']
        e_lfanew = headers.get('e_lfanew')
        if type(e_lfanew) is not int or not _in_range(base + e_lfanew, 0x18 + 60):
            return None, 'module'
        dos, error = _read(self.memory, base, 0x40)
        if error:
            return None, error
        pe, error = _read(self.memory, base + e_lfanew, 0x18 + 60)
        if error:
            return None, error
        token = (dos + pe).hex()
        if token != headers.get('header_hex'):
            return None, 'changed_module_header'
        return token, None

    def _budget(self):
        self.budget = True
        self.partial = True
        if not any(gap.get('reason') == 'budget' for gap in self.gaps):
            self.add_gap('budget')

    def _entry(self, item):
        queue, pointer, size, index = item
        slot = (queue, pointer, index)
        address = pointer + index * ENTRY_SIZE
        if not _in_range(address, ENTRY_SIZE):
            self.add_gap('address', queue=queue, entry=index)
            self.visited[slot] = None
            return
        entry, error = _read(self.memory, address, ENTRY_SIZE)
        if error:
            self.add_gap(error, queue=queue, entry=index)
            self.visited[slot] = None
            return
        metadata, payload_pointer, length = struct.unpack('<3I', entry)
        if length <= 0 or length > MAX_PAYLOAD:
            self.add_gap('payload_length', queue=queue, entry=index)
            self.visited[slot] = None
            return
        if not _in_range(payload_pointer, length):
            self.add_gap('address', queue=queue, entry=index)
            self.visited[slot] = None
            return
        previous = self.observer._slots.get(slot)
        if len(self.events) >= MAX_SAMPLE_EVENTS and previous is None:
            self.drops += 1
            self.add_gap('event_limit', queue=queue, entry=index)
            return
        if self.payload_bytes + length > MAX_SAMPLE_PAYLOAD:
            self.drops += 1
            self.partial = True
            self.stopped = True
            self.add_gap('payload_total', queue=queue, entry=index)
            return
        payload, error = _read(self.memory, payload_pointer, length)
        if error:
            self.add_gap(error, queue=queue, entry=index)
            self.visited[slot] = None
            return
        self.payload_bytes += length
        if not self._stable(address, entry, payload_pointer, length, payload):
            self.visited[slot] = None
            return
        digest = hashlib.sha256(payload).hexdigest()
        key = (queue, pointer, index, metadata, payload_pointer, length, digest)
        if previous == key:
            self.visited[slot] = key
            return
        if len(self.events) >= MAX_SAMPLE_EVENTS:
            self.drops += 1
            self.add_gap('event_limit', queue=queue, entry=index)
            return
        self.visited[slot] = key
        self.events.append(self._event(
            queue, pointer, size, index, address, entry, metadata, payload_pointer, length, payload, digest))

    def _stable(self, address, entry, payload_pointer, length, payload):
        again, error = _read(self.memory, address, ENTRY_SIZE)
        if error or again != entry:
            self.add_gap('changed_entry' if not error else error, entry_address=address)
            return False
        head, error = _read(self.memory, self._head_address(), HEAD_SIZE)
        if error or head != self.head:
            self.add_gap('changed_head' if not error else error)
            self.stopped = True
            self.partial = True
            return False
        check, error = _read(self.memory, payload_pointer, length)
        if error or check != payload:
            self.add_gap('changed_payload' if not error else error, payload_pointer=payload_pointer)
            return False
        token, error = self._token()
        if error or token != self.header:
            self.add_gap('changed_module_header')
            self.stopped = True
            self.partial = True
            return False
        if not _identity_matches(self.memory, self.observer.binding):
            self.add_gap('binding')
            self.stopped = True
            self.observer._slots = {}
            return False
        return True

    def _event(self, queue, pointer, size, index, address, entry, metadata, payload_pointer, length, payload, digest):
        read_index = self.head_values[2] if queue == 'primary' else None
        try:
            moment = self.observer._clock()
            captured = moment.isoformat() if isinstance(moment, datetime) else None
        except Exception:
            captured = None
        try:
            mono = int(self.observer._monotonic() * 1000000000)
        except Exception:
            mono = None
        return {
            'kind': 'network_payload_observation',
            'captured_at': captured,
            'monotonic_ns': mono,
            'sample': self.sample,
            'queue': queue,
            'context': self.observer.module['context'],
            'array': pointer,
            'queue_count': size,
            'read_index': read_index,
            'entry_index': index,
            'entry_address': address,
            'entry_hex': entry.hex(),
            'metadata_raw': metadata,
            'payload_pointer': payload_pointer,
            'payload_length': length,
            'raw_hex': payload.hex(),
            'raw_sha256': digest,
            'double_read_consistent': True,
            'atomic': False,
            'decoded_action': None,
            'actor_force_id': None,
            'target_lord_id': None,
            'submission_or_execution_verified': False,
            'action_training_eligible': False,
            'coverage': 'partial',
            'completeness': 'unknown',
            'absence_means_no_command': False,
            'read_only': True,
            'no_target_calls': True,
            'fake': self.observer._fake,
            'binding': deepcopy(self.observer.binding),
            'generation': self.observer.generation,
            'capture_session_is_match_id': False,
            'module': self.observer._module_evidence(),
            'limitations': list(LIMITATIONS),
        }

    def _commit_slots(self, plan):
        if any(gap.get('reason') in ('binding', 'changed_module_header') for gap in self.gaps):
            self.observer._slots = {}
            return
        if any(gap.get('reason') == 'changed_head' for gap in self.gaps):
            self.observer._slots = {slot: key for slot, key in self.visited.items() if key is not None}
            return
        if self.stopped or self.partial or self.budget:
            merged = {}
            live = {(queue, pointer, index) for queue, pointer, size, index in plan}
            for slot, key in self.observer._slots.items():
                if slot in self.visited:
                    continue
                if slot in live:
                    merged[slot] = key
            for slot, key in self.visited.items():
                if key is not None:
                    merged[slot] = key
            if len(merged) > MAX_CACHE_KEYS:
                self.drops += len(merged) - MAX_CACHE_KEYS
                self.add_gap('cache_limit')
                merged = dict(list(merged.items())[:MAX_CACHE_KEYS])
            self.observer._slots = merged
            return
        fresh = {slot: key for slot, key in self.visited.items() if key is not None}
        if len(fresh) > MAX_CACHE_KEYS:
            self.drops += len(fresh) - MAX_CACHE_KEYS
            self.add_gap('cache_limit')
            self.partial = True
            fresh = dict(list(fresh.items())[:MAX_CACHE_KEYS])
        self.observer._slots = fresh

    def _finish(self, status):
        reason = None
        if status == 'unknown':
            reason = self.gaps[-1]['reason'] if self.gaps else 'unknown'
        try:
            elapsed = self.observer._monotonic() - self.started
        except Exception:
            elapsed = None
        return self.observer._result(
            self.sample, status, reason, self.events, self.gaps, self.drops,
            self.partial, self.budget, self.truncated, elapsed)


def _module_evidence_mismatch(evidence, module):
    if module is None or not isinstance(evidence, dict):
        return 'module'
    if evidence.get('base') != module.get('base') or evidence.get('sha256') != module.get('sha256'):
        return 'module'
    if evidence.get('context') != module.get('context') or evidence.get('path') != module.get('path'):
        return 'module'
    if bool(evidence.get('fake')) != bool(module.get('fake')):
        return 'fake'
    return None


def _record_bytes(record):
    try:
        return len((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8'))
    except (TypeError, ValueError):
        return None


class PayloadJournal:
    """Append-only machine-local journal. close() only closes the file."""

    def __init__(self, root, binding, max_segment_bytes=MAX_SEGMENT_BYTES, max_session_bytes=MAX_SESSION_BYTES):
        parent = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        self.root = parent / DIRECTORY_NAME
        self.max_segment_bytes = max_segment_bytes if type(max_segment_bytes) is int and 1 <= max_segment_bytes <= MAX_SEGMENT_BYTES else MAX_SEGMENT_BYTES
        if type(max_session_bytes) is not int or max_session_bytes < 0:
            raise ValueError('max_session_bytes must be a nonnegative integer')
        self.max_session_bytes = min(max_session_bytes, MAX_SESSION_BYTES)
        self._binding = _binding_fields(binding)
        self._lock = threading.Lock()
        self._session = str(uuid.uuid4())
        self._segment = 0
        self._path = None
        self._handle = None
        self._size = 0
        self._samples = 0
        self._events = 0
        self._gaps = 0
        self._drops = 0
        self._dropped_records = 0
        self._write_failures = 0
        self._latched = set()
        self._held = set()
        self._module_base = None
        self._module_fake = None
        self._generation = None
        self._pending_uncertain = False
        self.write_error = None if self._binding else 'binding'
        self.last_write_error = None
        self.first_write_error = None
        self._journal_closed = False
        self._bytes_written = 0
        self._quota_exceeded = False

    def public_status(self):
        with self._lock:
            return {
                'directory_name': DIRECTORY_NAME,
                'capture_session_id': self._session,
                'capture_session_is_match_id': False,
                'segment': self._segment or None,
                'samples': self._samples,
                'events': self._events,
                'gaps': self._gaps,
                'drops': self._drops,
                'dropped_records': self._dropped_records,
                'write_failures': self._write_failures,
                'write_error': self.last_write_error or self.write_error,
                'last_write_error': self.last_write_error,
                'first_write_error': self.first_write_error,
                'bytes_written': self._bytes_written,
                'byte_accounting': 'reserved_upper_bound_including_failed_writes',
                'quota_exceeded': self._quota_exceeded,
                'fake': self._module_fake,
                'generation': self._generation,
                'capture_session_is_match_id': False,
                'journal_closed': self._journal_closed,
                'coverage': 'partial',
                'completeness': 'unknown',
                'absence_means_no_command': False,
                'read_only': True,
                'no_target_calls': True,
            }

    def close(self):
        try:
            with self._lock:
                self._close_handle()
                self._journal_closed = True
        except Exception as error:
            self.write_error = str(error)

    def ingest(self, poll, module, now=None):
        try:
            moment = _now(now)
        except Exception as error:
            self.write_error = str(error)
            return
        try:
            with self._lock:
                self._journal_closed = False
                self._ingest(poll, module, moment)
        except Exception as error:
            self.write_error = str(error)

    def _ingest(self, poll, module, now):
        self._samples += 1
        self._held = set()
        if self._binding is None:
            self.write_error = 'binding'
            return
        if not isinstance(poll, dict):
            self._note_gap(now, 'poll', None)
            return
        supplied = _binding_fields(poll.get('binding'))
        if supplied != self._binding:
            self._note_gap(now, 'binding', poll)
            return
        checked = _module_ok(module)
        module_reason = _module_evidence_mismatch(poll.get('module'), checked)
        if checked is None or module_reason:
            self._note_gap(now, module_reason or 'module', poll)
            return
        if self._module_base is None:
            self._module_base = checked['base']
            self._module_fake = bool(checked.get('fake'))
        elif checked['base'] != self._module_base or bool(checked.get('fake')) != self._module_fake:
            self._note_gap(now, 'module' if checked['base'] != self._module_base else 'fake', poll)
            return
        generation = poll.get('generation')
        if type(generation) is not str or not generation or len(generation) > 64:
            self._note_gap(now, 'generation', poll)
            return
        if self._generation is None:
            self._generation = generation
        elif generation != self._generation:
            self._note_gap(now, 'generation', poll)
            return
        status = poll.get('status')
        drops = poll.get('drop_count')
        if type(drops) is int and not isinstance(drops, bool) and 0 < drops <= 1000000:
            self._drops += drops
        events = poll.get('events')
        gaps = poll.get('gaps')
        if events is not None and not isinstance(events, list):
            self._note_gap(now, 'poll', poll)
            return
        if gaps is not None and not isinstance(gaps, list):
            self._note_gap(now, 'poll', poll)
            return
        if isinstance(events, list) and len(events) > MAX_SAMPLE_EVENTS:
            events = events[:MAX_SAMPLE_EVENTS]
            self._note_gap(now, 'event_limit', poll)
        lost = 0
        if status != 'unknown':
            for event in events or []:
                if not self._event_source_ok(event, checked):
                    self._note_gap(now, 'binding', poll)
                    continue
                if not self._write_event(event, checked, now):
                    lost += 1
        if lost:
            self._dropped_records += lost
            self._drops += lost
            self._note_gap(now, 'write_loss', poll)
        reasons = []
        seen = set()
        for gap in (gaps or [])[:MAX_GAPS]:
            reason = gap.get('reason') if isinstance(gap, dict) else None
            if type(reason) is not str or not reason or reason in seen or len(reason) > 64:
                continue
            seen.add(reason)
            reasons.append(reason)
        if status == 'unknown' and not reasons:
            reason = poll.get('reason') if type(poll.get('reason')) is str and poll.get('reason') else 'unknown'
            if len(reason) <= 64:
                reasons.append(reason)
        if status == 'unknown':
            kept = set(self._latched)
            kept.update(self._held)
            for reason in reasons:
                if reason in self._latched or self._gap(now, reason, poll):
                    kept.add(reason)
            self._latched = kept
            return
        kept = set(self._held)
        for reason in reasons:
            if reason in self._latched or self._gap(now, reason, poll):
                kept.add(reason)
        self._latched = kept

    def _labels(self):
        return {
            'schema': SCHEMA,
            'fake': self._module_fake,
            'capture_session_id': self._session,
            'capture_session_is_match_id': False,
            'source_id': self._binding['source_id'],
            'build': self._binding['build'],
            'core': self._binding['core'],
            'image': self._binding['image'],
            'target': {
                'pid': self._binding['pid'],
                'creation_filetime': self._binding['created'],
                'path': self._binding['image'],
            },
            'coverage': 'partial',
            'completeness': 'unknown',
            'absence_means_no_command': False,
            'decoded_action': None,
            'actor_force_id': None,
            'target_lord_id': None,
            'submission_or_execution_verified': False,
            'action_training_eligible': False,
            'read_only': True,
            'no_target_calls': True,
            'limitations': list(LIMITATIONS),
        }

    def _module_view(self, module):
        return {
            'base': module['base'],
            'path': module['path'],
            'sha256': module['sha256'],
            'context': module['context'],
            'fake': bool(module.get('fake')),
        }

    def _write_event(self, event, module, now):
        if not isinstance(event, dict):
            self._gap(now, 'event', None)
            return False
        raw_hex = event.get('raw_hex')
        if type(raw_hex) is not str or len(raw_hex) > MAX_PAYLOAD * 2 or len(raw_hex) % 2:
            self._note_gap(now, 'payload', None)
            self._remember_write_error('record exceeds %d bytes' % MAX_RECORD_BYTES, seal=False)
            return False
        try:
            raw = bytes.fromhex(raw_hex)
        except ValueError:
            self._note_gap(now, 'payload', None)
            return False
        digest = hashlib.sha256(raw).hexdigest()
        if event.get('raw_sha256') != digest or len(raw) <= 0 or len(raw) > MAX_PAYLOAD:
            self._note_gap(now, 'payload_sha', None)
            return False
        record = self._labels()
        record.update({
            'kind': 'network_payload_observation',
            'observed_at': now.isoformat(),
            'captured_at': event.get('captured_at') if type(event.get('captured_at')) is str else None,
            'module': self._module_view(module),
            'sample': event.get('sample') if type(event.get('sample')) is int else None,
            'queue': event.get('queue') if event.get('queue') in ('primary', 'alternate') else None,
            'context': module['context'],
            'array': event.get('array') if type(event.get('array')) is int else None,
            'queue_count': event.get('queue_count') if type(event.get('queue_count')) is int else None,
            'read_index': event.get('read_index') if type(event.get('read_index')) is int else None,
            'entry_index': event.get('entry_index') if type(event.get('entry_index')) is int else None,
            'entry_address': event.get('entry_address') if type(event.get('entry_address')) is int else None,
            'entry_hex': event.get('entry_hex') if type(event.get('entry_hex')) is str and len(event.get('entry_hex')) == ENTRY_SIZE * 2 else None,
            'metadata_raw': event.get('metadata_raw') if type(event.get('metadata_raw')) is int else None,
            'payload_pointer': event.get('payload_pointer') if type(event.get('payload_pointer')) is int else None,
            'payload_length': len(raw),
            'raw_hex': raw_hex,
            'raw_sha256': digest,
            'fake': True if module.get('fake') else False,
            'binding': deepcopy(self._binding),
            'generation': self._generation,
            'capture_session_is_match_id': False,
        })
        # Labels stay unknown even if the caller attached an action.
        record['decoded_action'] = None
        record['actor_force_id'] = None
        record['target_lord_id'] = None
        record['submission_or_execution_verified'] = False
        record['action_training_eligible'] = False
        if self._write(record, 'events'):
            return True
        return False

    def _event_source_ok(self, event, module):
        if not isinstance(event, dict):
            return False
        if _binding_fields(event.get('binding')) != self._binding:
            return False
        if event.get('generation') != self._generation:
            return False
        if event.get('capture_session_is_match_id') is True:
            return False
        if _module_evidence_mismatch(event.get('module'), module):
            return False
        if bool(event.get('fake')) != bool(module.get('fake')):
            return False
        return True

    def _remember_write_error(self, message, seal):
        self._write_failures += 1
        if self.first_write_error is None:
            self.first_write_error = message
        self.last_write_error = message
        self.write_error = message
        if seal:
            self._pending_uncertain = True
            self._close_handle()

    def _note_gap(self, now, reason, poll):
        self._held.add(reason)
        if reason in self._latched:
            return False
        if self._gap(now, reason, poll):
            self._latched.add(reason)
            return True
        return False

    def _gap(self, now, reason, poll):
        if self._binding is None:
            self.write_error = 'binding'
            return False
        record = self._labels()
        record.update({
            'kind': 'network_payload_gap',
            'reason': reason,
            'observed_at': now.isoformat(),
            'sample': poll.get('sample') if isinstance(poll, dict) and type(poll.get('sample')) is int else None,
            'drops': self._drops,
            'dropped_records': self._dropped_records,
            'write_failures': self._write_failures,
            'generation': self._generation,
            'capture_session_is_match_id': False,
        })
        return self._write(record, 'gaps')

    def _mark_quota(self):
        if self._quota_exceeded:
            return
        self._quota_exceeded = True
        self._write_failures += 1
        if self.first_write_error is None:
            self.first_write_error = 'session_quota'
        self.last_write_error = 'session_quota'
        self.write_error = 'session_quota'

    def _write(self, record, counter):
        if self._quota_exceeded:
            return False
        encoded = _record_bytes(record)
        if encoded is None or encoded > MAX_RECORD_BYTES or encoded > self.max_segment_bytes:
            self._remember_write_error('record exceeds %d bytes' % MAX_RECORD_BYTES, seal=False)
            return False
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
            data = line.encode('utf-8')
            if len(data) != encoded:
                self._remember_write_error('record exceeds %d bytes' % MAX_RECORD_BYTES, seal=False)
                return False
            if self._pending_uncertain:
                self._open_next()
                if self._quota_exceeded or self._handle is None:
                    return False
            if self._bytes_written + len(data) > self.max_session_bytes:
                self._mark_quota()
                return False
            if self._handle is None or self._size + len(data) > self.max_segment_bytes:
                self._open_next()
            if self._handle is None:
                if not self._quota_exceeded:
                    self._remember_write_error(self.last_write_error or 'segment_closed', seal=False)
                return False
            if self._bytes_written + len(data) > self.max_session_bytes:
                self._mark_quota()
                return False
            # Charge the entire request before I/O: even an exception/short
            # write can leave physical bytes in the sealed segment. Never
            # reclaim that uncertain reservation on recovery.
            self._bytes_written += len(data)
            written = self._handle.write(line)
            if written is not None and written < len(line):
                self._remember_write_error('short_write', seal=True)
                return False
            self._handle.flush()
            self._size += len(data)
            if counter == 'events':
                self._events += 1
            elif counter == 'gaps':
                self._gaps += 1
            return True
        except Exception as error:
            self._remember_write_error(str(error), seal=True)
            return False

    def _open_next(self):
        self._close_handle()
        if self._binding is None:
            raise OSError('binding')
        digest = hashlib.sha256(json.dumps(self._binding, sort_keys=True).encode('utf-8')).hexdigest()[:20]
        directory = self.root / digest
        directory.mkdir(parents=True, exist_ok=True)
        while True:
            self._segment += 1
            if self._segment > 100000:
                raise OSError('segment_limit')
            path = directory / ('%s-seg-%04d.jsonl' % (self._session, self._segment))
            if not path.exists():
                break
        self._path = path
        self._handle = path.open('a', encoding='utf-8', newline='\n')
        self._size = path.stat().st_size
        if self._pending_uncertain:
            self._pending_uncertain = False
            self._write_uncertain()

    def _write_uncertain(self):
        record = self._labels()
        record.update({
            'kind': 'network_payload_gap',
            'reason': 'uncertain_omission',
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'sample': None,
            'drops': self._drops,
            'dropped_records': self._dropped_records,
            'write_failures': self._write_failures,
            'generation': self._generation,
            'capture_session_is_match_id': False,
            'completeness': 'unknown',
        })
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
        except (TypeError, ValueError) as error:
            self.last_write_error = str(error)
            self.write_error = str(error)
            self._close_handle()
            return
        encoded = line.encode('utf-8')
        if self._quota_exceeded or self._bytes_written + len(encoded) > self.max_session_bytes:
            self._mark_quota()
            self._close_handle()
            return
        try:
            self._bytes_written += len(encoded)
            written = self._handle.write(line)
            if written is not None and written < len(line):
                raise OSError('short_write')
            self._handle.flush()
            self._size += len(encoded)
            self._gaps += 1
        except Exception as error:
            self._write_failures += 1
            if self.first_write_error is None:
                self.first_write_error = str(error)
            self.last_write_error = str(error)
            self.write_error = str(error)
            self._close_handle()

    def _close_handle(self):
        handle = self._handle
        self._handle = None
        if handle is not None:
            handle.close()
