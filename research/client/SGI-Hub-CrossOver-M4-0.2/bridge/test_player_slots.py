"""Fake-memory tests for the verified lobby-nickname slot reader."""
import inspect
import json
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import collector
import player_slots
from player_slots import (
    CORE_LIMIT, CORE_MIN, EMPTY_LABEL, SLOT_BASE, SLOT_BYTES, SLOT_COUNT, SLOT_STRIDE,
    VERIFIED_BUILD, display_nickname, read_player_slots, read_player_slots_bound,
)

CORE = 0x400000
RAW = bytes.fromhex('baabc1a228d6febbf9baf3c6da29')
OTHER = 'NOTNICK'.encode('ascii')


class Sparse:
    def __init__(self):
        self.mem = {}
        self.calls = []
        self.raise_at = set()
        self.flip = {}
        self.flip_on = {}

    def write(self, address, data):
        for index, value in enumerate(data):
            self.mem[address + index] = value

    def read(self, address, size):
        self.calls.append((address, size))
        if address in self.raise_at:
            raise OSError('injected')
        if any(address + index not in self.mem for index in range(size)):
            return None
        data = bytes(self.mem[address + index] for index in range(size))
        seen = self.flip.get(address, 0) + 1
        self.flip[address] = seen
        if self.flip_on.get(address) == seen:
            return bytes([data[0] ^ 0xFF]) + data[1:]
        return data


def slot_address(slot, core=CORE):
    return core + 4 + slot * 0x87


def plant_slot(mem, slot, source, state, force, nickname, other=b'', core=CORE):
    base = slot_address(slot, core)
    name_ptr = 0x500000 + slot * 0x200
    other_ptr = name_ptr + 0x100
    blob = bytearray(SLOT_BYTES)
    struct.pack_into('<I', blob, 6, source)
    struct.pack_into('<I', blob, 0x0A, other_ptr)
    struct.pack_into('<I', blob, 0x0E, nickname)
    struct.pack_into('<I', blob, 0x42, state)
    struct.pack_into('<I', blob, 0x46, force)
    mem.write(base, bytes(blob))
    plant_string(mem, other_ptr, other)
    return name_ptr


def plant_string(mem, pointer, raw, capacity=None):
    if capacity is None:
        capacity = len(raw)
    mem.write(pointer - 12, struct.pack('<iii', 1, len(raw), capacity))
    mem.write(pointer, raw + b'\0')


def plant_name(mem, slot, source, state, force, raw, capacity=None, core=CORE):
    pointer = 0x500000 + slot * 0x200
    plant_slot(mem, slot, source, state, force, pointer, core=core)
    plant_string(mem, pointer, raw, capacity)
    return pointer


def snapshot(view, build=VERIFIED_BUILD):
    return {
        'build_sha256': build,
        'identity': {'pid': 1, 'path': 'SANPK.exe'},
        'player_context': {'force_id': 7, 'slot': 0, 'status': 'verified', 'source': 'game_player_context'},
        'player_slots': view['player_slots'],
        'player_slots_layout': view['layout'],
    }


class PlayerSlotTests(unittest.TestCase):
    def test_gbk_fixture_distinguishes_acp_936_from_950(self):
        self.assertEqual(RAW.decode('gbk'), '韩立(筑基后期)')
        self.assertNotEqual(RAW.decode('cp950'), RAW.decode('gbk'))
        mem = Sparse()
        plant_name(mem, 0, 182562834, 0, 7, RAW)
        lords = [{'force_id': 7, 'name': '晋'}]
        with patch('player_slots.read_target_nls_ansi_code_page', side_effect=AssertionError('target queried')):
            view = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
        row = view['player_slots'][0]
        self.assertEqual(row['nickname'], '韩立(筑基后期)')
        self.assertEqual(row['encoding'], 'cp936')
        self.assertEqual(row['raw_hex'], RAW.hex())
        self.assertEqual(row['status'], 'confirmed')
        self.assertEqual(row['source_metadata'], 182562834)
        self.assertTrue(all(row['stability'].values()))
        self.assertEqual(view['layout']['build_sha256'], VERIFIED_BUILD)
        self.assertEqual(view['layout']['ansi_code_page'], 936)
        self.assertEqual(view['layout']['ansi_code_page_source'], 'explicit_test_parameter')
        self.assertFalse(view['layout']['target_ansi_code_page_directly_observed'])
        self.assertFalse(view['layout']['target_code_executed'])
        self.assertIn('activeCodePage', view['layout']['decoding_limitation'])
        self.assertIn('not a fallback', view['layout']['decoding_limitation'])
        self.assertEqual(display_nickname(snapshot(view), 7), '韩立(筑基后期)')
        traditional = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=950)
        self.assertEqual(traditional['player_slots'][0]['nickname'], RAW.decode('cp950'))
        self.assertNotEqual(traditional['player_slots'][0]['nickname'], '韩立(筑基后期)')
        self.assertEqual(traditional['player_slots'][0]['encoding'], 'cp950')

    def test_without_acp_bytes_stay_undecoded(self):
        mem = Sparse()
        plant_name(mem, 0, 182562834, 0, 7, RAW)
        with patch('player_slots.read_target_nls_ansi_code_page', return_value=None):
            view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}])
        row = view['player_slots'][0]
        self.assertIsNone(row['nickname'])
        self.assertIsNone(row['encoding'])
        self.assertEqual(row['raw_hex'], RAW.hex())
        self.assertEqual(row['reason'], 'code_page_unavailable')
        self.assertEqual(view['layout']['ansi_code_page_source'], 'target_ntdll_unavailable')
        self.assertIsNone(view['layout']['ansi_code_page'])
        self.assertFalse(view['layout']['target_ansi_code_page_directly_observed'])
        self.assertFalse(view['layout']['target_code_executed'])
        self.assertIsNone(display_nickname(snapshot(view), 7))
        self.assertNotEqual(row['raw_hex'], '')
        self.assertNotIn('韩立', json.dumps(row, ensure_ascii=False))

    def test_target_936_decodes_and_helper_1252_is_not_used(self):
        mem = Sparse()
        plant_name(mem, 0, 182562834, 0, 7, RAW)
        mem.h = 1
        raw = struct.pack('<H', 936)
        evidence = {
            'codepage': 936,
            'module_path': 'C:\\windows\\system32\\ntdll.dll',
            'module_base': 2079588352,
            'export_rva': 603876,
            'raw_hex': raw.hex(),
            'double_read': True,
            'read_only': True,
            'target_code_executed': False,
            'source': 'target_ntdll_NlsAnsiCodePage',
        }
        with patch('player_slots.read_target_nls_ansi_code_page', return_value=evidence):
            view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}])
        row = view['player_slots'][0]
        self.assertEqual(row['nickname'], '韩立(筑基后期)')
        self.assertEqual(row['encoding'], 'cp936')
        self.assertNotEqual(row['nickname'], RAW.decode('cp1252'))
        self.assertEqual(view['layout']['ansi_code_page'], 936)
        self.assertEqual(view['layout']['ansi_code_page_source'], 'target_ntdll_NlsAnsiCodePage')
        self.assertTrue(view['layout']['target_ansi_code_page_directly_observed'])
        self.assertFalse(view['layout']['target_code_executed'])
        self.assertEqual(view['layout']['ansi_code_page_evidence']['export_rva'], 603876)
        self.assertEqual(view['layout']['ansi_code_page_evidence']['raw_hex'], raw.hex())
        self.assertEqual(display_nickname(snapshot(view), 7), '韩立(筑基后期)')

    def test_other_string_slot_is_not_the_nickname(self):
        mem = Sparse()
        pointer = plant_name(mem, 0, 1, 0, 7, RAW)
        blob = bytearray(mem.read(slot_address(0), SLOT_BYTES))
        mem.calls.clear()
        struct.pack_into('<I', blob, 0x0A, pointer + 0x80)
        mem.write(slot_address(0), bytes(blob))
        plant_string(mem, pointer + 0x80, OTHER)
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936)
        self.assertEqual(view['player_slots'][0]['nickname'], '韩立(筑基后期)')
        self.assertNotIn(OTHER.hex(), view['player_slots'][0]['raw_hex'])

    def test_empty_nickname_is_unknown_and_labeled_only_for_display(self):
        mem = Sparse()
        plant_name(mem, 0, 5, 0, 7, b'')
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936)
        row = view['player_slots'][0]
        self.assertEqual(row['status'], 'unknown')
        self.assertEqual(row['reason'], 'empty_nickname')
        self.assertIsNone(row['nickname'])
        self.assertEqual(row['raw_hex'], '')
        self.assertEqual(display_nickname(snapshot(view), 7), EMPTY_LABEL)
        self.assertIsNone(display_nickname(snapshot(view), 1))

    def test_bad_pointer_length_and_capacity_stay_unknown(self):
        lords = [{'force_id': 7}]
        mem = Sparse()
        plant_slot(mem, 0, 1, 0, 7, 0x1000B)
        low = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
        self.assertEqual(low['player_slots'][0]['reason'], 'pointer_out_of_bounds')
        self.assertIsNone(low['player_slots'][0]['nickname'])
        self.assertTrue(all(size <= SLOT_BYTES for _, size in mem.calls))

        mem = Sparse()
        plant_slot(mem, 0, 1, 0, 7, 0x7FFEFF00)
        high = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
        self.assertEqual(high['player_slots'][0]['reason'], 'pointer_out_of_bounds')

        for length, capacity in ((129, 129), (1, 4097), (5, 4), (-1, 8)):
            mem = Sparse()
            pointer = 0x500000
            plant_slot(mem, 0, 1, 0, 7, pointer)
            mem.write(pointer - 12, struct.pack('<iii', 1, length, capacity))
            if 0 <= length <= 8:
                mem.write(pointer, b'x' * length + b'\0')
            view = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
            self.assertEqual(view['player_slots'][0]['reason'], 'invalid_cstring_header', (length, capacity))
            self.assertIsNone(view['player_slots'][0]['raw_hex'])
            self.assertTrue(all(size <= SLOT_BYTES for _, size in mem.calls))

        mem = Sparse()
        plant_name(mem, 0, 1, 0, 7, b'A' * 128, capacity=4096)
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
        self.assertEqual(view['player_slots'][0]['nickname'], 'A' * 128)
        self.assertTrue(all(size <= 129 for _, size in mem.calls))

    def test_second_read_change_discards_the_first(self):
        mem = Sparse()
        pointer = plant_name(mem, 0, 182562834, 0, 7, RAW)
        mem.flip_on[pointer] = 2
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936)
        row = view['player_slots'][0]
        self.assertIsNone(row['nickname'])
        self.assertIsNone(row['raw_hex'])
        self.assertEqual(row['reason'], 'unstable')
        self.assertGreaterEqual(sum(1 for addr, _ in mem.calls if addr == pointer), 2)
        self.assertIsNone(display_nickname(snapshot(view), 7))

        mem = Sparse()
        plant_name(mem, 0, 182562834, 0, 7, RAW)
        mem.flip_on[slot_address(0)] = 2
        shifted = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936)
        self.assertIsNone(shifted['player_slots'][0]['source_metadata'])
        self.assertIsNone(shifted['player_slots'][0]['nickname'])
        self.assertEqual(shifted['player_slots'][0]['reason'], 'unstable')

    def test_change_after_local_pairs_rejects_the_row(self):
        lords = [{'force_id': 7}]
        mem = Sparse()
        plant_name(mem, 0, 182562834, 0, 7, RAW)
        mem.flip_on[slot_address(0)] = 3
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
        row = view['player_slots'][0]
        self.assertGreaterEqual(sum(1 for addr, _ in mem.calls if addr == slot_address(0)), 3)
        self.assertIsNone(row['nickname'])
        self.assertIsNone(row['raw_hex'])
        self.assertIsNone(row['force_id'])
        self.assertIsNone(row['source_metadata'])
        self.assertEqual(row['status'], 'unknown')
        self.assertEqual(row['reason'], 'unstable')
        self.assertFalse(any(row['stability'].values()))
        self.assertIsNone(display_nickname(snapshot(view), 7))

        mem = Sparse()
        pointer = plant_name(mem, 0, 182562834, 0, 7, RAW)
        mem.flip_on[pointer - 12] = 3
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, lords, ansi_code_page=936)
        row = view['player_slots'][0]
        self.assertGreaterEqual(sum(1 for addr, _ in mem.calls if addr == pointer - 12), 3)
        self.assertIsNone(row['nickname'])
        self.assertIsNone(row['raw_hex'])
        self.assertIsNone(row['force_id'])
        self.assertEqual(row['reason'], 'unstable')
        self.assertIsNone(display_nickname(snapshot(view), 7))

    def test_core_range_includes_eight_slots_and_rejects_bool(self):
        span = SLOT_BASE + (SLOT_COUNT - 1) * SLOT_STRIDE + SLOT_BYTES
        lords = [{'force_id': 7}]
        rejected = (True, False, 0, -1, CORE_MIN - 1, CORE_LIMIT, CORE_LIMIT - span + 1, 2 ** 32)
        for core in rejected:
            mem = Sparse()
            view = read_player_slots(mem, core, VERIFIED_BUILD, lords, ansi_code_page=936)
            self.assertEqual(mem.calls, [], core)
            self.assertEqual(len(view['player_slots']), 8)
            self.assertTrue(all(row['reason'] == 'invalid_core' and row['nickname'] is None for row in view['player_slots']))
            self.assertFalse(view['layout']['target_ansi_code_page_directly_observed'])
        for core in (CORE_MIN, CORE_LIMIT - span):
            mem = Sparse()
            plant_name(mem, 0, 182562834, 0, 7, RAW, core=core)
            view = read_player_slots(mem, core, VERIFIED_BUILD, lords, ansi_code_page=936)
            self.assertEqual(view['player_slots'][0]['nickname'], '韩立(筑基后期)', hex(core))
            self.assertEqual(display_nickname(snapshot(view), 7), '韩立(筑基后期)')

    def test_duplicate_force_and_bool_lord_do_not_confirm(self):
        mem = Sparse()
        plant_name(mem, 0, 1, 0, 7, RAW)
        plant_name(mem, 1, 2, 0, 7, b'OTHER')
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936)
        self.assertEqual(view['player_slots'][0]['reason'], 'duplicate_force')
        self.assertEqual(view['player_slots'][1]['reason'], 'duplicate_force')
        self.assertIsNone(view['player_slots'][0]['nickname'])
        self.assertIsNone(display_nickname(snapshot(view), 7))

        mem = Sparse()
        plant_name(mem, 0, 1, 0, 1, RAW)
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': True}], ansi_code_page=936)
        self.assertEqual(view['player_slots'][0]['force_id'], 1)
        self.assertEqual(view['player_slots'][0]['reason'], 'invalid_force')
        self.assertIsNone(view['player_slots'][0]['nickname'])
        self.assertIsNone(display_nickname(snapshot(view), 1))
        self.assertIsNone(display_nickname(snapshot(view), True))

        mem = Sparse()
        plant_name(mem, 0, 1, 0, 7, RAW)
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}, {'force_id': 7}], ansi_code_page=936)
        self.assertEqual(view['player_slots'][0]['reason'], 'duplicate_lord')
        self.assertIsNone(display_nickname(snapshot(view), 7))

    def test_unknown_build_does_not_read_memory(self):
        mem = Sparse()
        plant_name(mem, 0, 1, 0, 7, RAW)
        view = read_player_slots(mem, CORE, collector.BUILD, [{'force_id': 7}], ansi_code_page=936)
        self.assertEqual(mem.calls, [])
        self.assertEqual(view['player_slots'], [])
        self.assertEqual(view['layout']['status'], 'unknown')
        self.assertFalse(view['layout']['verified'])
        self.assertIn('未验证', view['layout']['note'])
        self.assertEqual(view['layout']['build_sha256'], collector.BUILD)
        self.assertIsNone(display_nickname(snapshot(view, collector.BUILD), 7))
        self.assertNotEqual(collector.BUILD, VERIFIED_BUILD)
        self.assertEqual(collector.DESTRUCTOR_HOTFIX_BUILD, VERIFIED_BUILD)

    def test_one_slot_exception_keeps_the_other_slot(self):
        mem = Sparse()
        plant_name(mem, 0, 182562834, 0, 7, RAW)
        plant_name(mem, 4, 9, 0, 3, '甲'.encode('gbk'))
        mem.raise_at.add(slot_address(4))
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}, {'force_id': 3}], ansi_code_page=936)
        self.assertEqual(view['player_slots'][0]['nickname'], '韩立(筑基后期)')
        self.assertEqual(view['player_slots'][4]['status'], 'unknown')
        self.assertEqual(view['player_slots'][4]['reason'], 'read_error')
        self.assertIsNone(view['player_slots'][4]['nickname'])
        self.assertEqual(len(view['player_slots']), 8)

    def test_source_zero_and_state_two_are_not_relabeled(self):
        mem = Sparse()
        plant_name(mem, 1, 0, 2, 4, b'')
        view = read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 4}], ansi_code_page=936)
        row = view['player_slots'][1]
        text = json.dumps(row, ensure_ascii=False)
        self.assertEqual(row['source_metadata'], 0)
        self.assertEqual(row['state_raw'], 2)
        self.assertNotIn('account_id', row)
        self.assertNotIn('账号', text)
        self.assertNotIn('AI', text)
        self.assertNotIn('电脑', text)
        self.assertIn('not a proven account id', row['static_source']['source_metadata'])
        self.assertEqual(display_nickname(snapshot(view), 4), EMPTY_LABEL)

    def test_reader_crash_does_not_raise_and_display_follows_current_snapshot(self):
        with patch('player_slots.read_player_slots', side_effect=RuntimeError('boom')):
            view = read_player_slots_bound(Sparse(), CORE, VERIFIED_BUILD, [{'force_id': 7}])
        self.assertEqual(view['player_slots'], [])
        self.assertEqual(view['layout']['status'], 'unknown')
        self.assertEqual(view['layout']['build_sha256'], VERIFIED_BUILD)
        self.assertIn('未知', view['layout']['note'])

        mem = Sparse()
        plant_name(mem, 0, 1, 0, 7, RAW)
        first = snapshot(read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936))
        second = snapshot(read_player_slots(Sparse(), CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=936))
        self.assertEqual(display_nickname(first, 7), '韩立(筑基后期)')
        self.assertIsNone(display_nickname(second, 7))
        self.assertEqual(display_nickname(first, 7), '韩立(筑基后期)')

    def test_capture_reads_process_memory_and_keeps_player_context_shape(self):
        source = inspect.getsource(collector.Collector.capture)
        self.assertIn("read_player_slots_bound(self.m,self.core,self.sha,entities['lords'])", source)
        self.assertNotIn('read_player_slots_bound(self.read', source)
        self.assertIn("'player_context':player_context", source)
        self.assertIn("'player_slots':slot_view['player_slots']", source)
        self.assertIn("'identity':self.m.identity", source)
        self.assertIn("'build_sha256':self.sha", source)

    def test_display_rejects_legacy_helper_codepage_attribution(self):
        mem = Sparse()
        plant_name(mem, 0, 1, 0, 7, RAW)
        doc = snapshot(read_player_slots(mem, CORE, VERIFIED_BUILD, [{'force_id': 7}], ansi_code_page=1252))
        doc['player_slots_layout']['ansi_code_page_source'] = 'collector_process_GetACP'
        self.assertIsNone(display_nickname(doc, 7))
        self.assertEqual(doc['player_slots'][0]['raw_hex'], RAW.hex())
        doc['player_slots_layout']['ansi_code_page_source'] = 'target_ntdll_NlsAnsiCodePage'
        doc['player_slots_layout']['target_ansi_code_page_directly_observed'] = False
        self.assertIsNone(display_nickname(doc, 7))

    def test_heading_and_identity_use_only_the_current_nickname(self):
        app = Path(__file__).resolve().parent.parent / 'app'
        if str(app) not in sys.path:
            sys.path.insert(0, str(app))
        from omni_window import force_heading_text, identity_text
        self.assertEqual(identity_text('晋', '自动识别', True, '韩立(筑基后期)'),
                         '我方：晋 · 自动识别 · 韩立(筑基后期) · 持续跟随游戏')
        self.assertEqual(identity_text('晋', '自动识别', True, EMPTY_LABEL),
                         '我方：晋 · 自动识别 · 大厅昵称未提供 · 持续跟随游戏')
        self.assertEqual(identity_text('晋', '未确认', False, None),
                         '我方：晋 · 未确认 · 识别不足时可手动确认')
        self.assertEqual(force_heading_text('晋', '我军', '韩立(筑基后期)'), '晋　我军　韩立(筑基后期)')
        self.assertEqual(force_heading_text('晋', '其他势力', EMPTY_LABEL), '晋　其他势力　大厅昵称未提供')
        self.assertEqual(force_heading_text('晋', '其他势力', None), '晋　其他势力')


if __name__ == '__main__':
    unittest.main()
