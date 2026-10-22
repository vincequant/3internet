"""Fake PE tests for the target ntdll NlsAnsiCodePage reader."""
import ctypes
from ctypes import wintypes
import struct
import unittest
from unittest.mock import patch

import player_slots
from target_codepage import LIST_MODULES_ALL, MAX_MODULES, read_target_nls_ansi_code_page

BASE = 0x20000000
PATH = 'C:\\windows\\system32\\ntdll.dll'
RAW_NICK = bytes.fromhex('baabc1a228d6febbf9baf3c6da29')


def build_image(codepage=936):
    image = bytearray(0x1000)
    image[0:2] = b'MZ'
    e_lfanew = 0x80
    struct.pack_into('<I', image, 0x3c, e_lfanew)
    image[e_lfanew:e_lfanew + 4] = b'PE\0\0'
    struct.pack_into('<H', image, e_lfanew + 4, 0x14c)
    struct.pack_into('<H', image, e_lfanew + 20, 0xE0)
    struct.pack_into('<H', image, e_lfanew + 24, 0x10b)
    struct.pack_into('<I', image, e_lfanew + 24 + 56, len(image))
    struct.pack_into('<I', image, e_lfanew + 24 + 92, 16)
    export_rva, export_size = 0x200, 40
    struct.pack_into('<II', image, e_lfanew + 24 + 96, export_rva, export_size)
    functions, names = 3, 3
    function_table, name_table, ordinal_table = 0x280, 0x2A0, 0x2C0
    struct.pack_into('<IIIII', image, export_rva + 20, functions, names, function_table, name_table, ordinal_table)
    strings = (0x300, 0x320, 0x340)
    labels = (b'Abc', b'NlsAnsiCodePage', b'Zzz')
    value_rva = 0x400
    function_rvas = (0x3F0, value_rva, 0x3F8)
    for index, (name_rva, label, function_rva) in enumerate(zip(strings, labels, function_rvas)):
        image[name_rva:name_rva + len(label) + 1] = label + b'\0'
        struct.pack_into('<I', image, name_table + 4 * index, name_rva)
        struct.pack_into('<H', image, ordinal_table + 2 * index, index)
        struct.pack_into('<I', image, function_table + 4 * index, function_rva)
        struct.pack_into('<H', image, function_rva, 1)
    struct.pack_into('<H', image, value_rva, codepage)
    return image, value_rva, export_rva


class ImageMemory:
    def __init__(self, image, handle=1):
        self.h = handle
        self.base = BASE
        self.image = bytearray(image)
        self.reads = []
        self.seen = {}
        self.flip_on = {}

    def read(self, address, size):
        self.reads.append((address, size))
        if type(address) is not int or type(size) is not int or size < 0 or address < self.base:
            return None
        rel = address - self.base
        if rel + size > len(self.image):
            return None
        data = bytes(self.image[rel:rel + size])
        self.seen[address] = self.seen.get(address, 0) + 1
        if self.flip_on.get(address) == self.seen[address]:
            return bytes([data[0] ^ 0xFF]) + data[1:]
        return data


def listed(handle):
    return [(BASE, PATH)]


class FakePsapi:
    def __init__(self, base=BASE, path=PATH, needed_extra=0):
        self.base = base
        self.path = path
        self.needed_extra = needed_extra
        self.flag = None
        self.cb = None

    def EnumProcessModulesEx(self, handle, modules, cb, needed, flag):
        self.flag = flag
        self.cb = cb
        modules[0] = self.base
        width = ctypes.sizeof(wintypes.HMODULE)
        needed._obj.value = width + self.needed_extra
        return 1

    def GetModuleFileNameExW(self, handle, module, buffer, size):
        if int(module) != self.base:
            return 0
        buffer.value = self.path
        return len(self.path)


class TargetCodePageTests(unittest.TestCase):
    def test_fake_pe_is_936_and_helper_1252_is_ignored(self):
        image, value_rva, _ = build_image(936)
        mem = ImageMemory(image)
        calls = []

        def win_dll(name, use_last_error=True):
            calls.append(name)
            if name.lower() == 'kernel32':
                return type('Kernel', (), {'GetACP': lambda self: 1252})()
            raise OSError(name)

        with patch('target_codepage.ctypes.WinDLL', win_dll, create=True):
            found = read_target_nls_ansi_code_page(mem, enumerate_modules=listed)
        self.assertEqual(calls, [])
        self.assertEqual(found['codepage'], 936)
        self.assertEqual(found['raw'], struct.pack('<H', 936))
        self.assertEqual(found['export_rva'], value_rva)
        self.assertEqual(found['module_base'], BASE)
        self.assertEqual(found['module_path'], PATH)
        self.assertTrue(found['double_read'])
        self.assertTrue(found['read_only'])
        self.assertFalse(found['target_code_executed'])
        self.assertEqual(found['source'], 'target_ntdll_NlsAnsiCodePage')
        self.assertTrue(all(size <= 4096 for _, size in mem.reads))
        self.assertLess(sum(size for _, size in mem.reads), len(image))
        self.assertNotIn(len(image), [size for _, size in mem.reads])

        mem.image[value_rva:value_rva + 2] = struct.pack('<H', 950)
        again = read_target_nls_ansi_code_page(mem, enumerate_modules=listed)
        self.assertEqual(again['codepage'], 950)

    def test_psapi_lists_at_most_1024_modules_with_list_modules_all(self):
        image, _, _ = build_image()
        mem = ImageMemory(image)
        psapi = FakePsapi()
        found = read_target_nls_ansi_code_page(mem, psapi=psapi)
        self.assertEqual(psapi.flag, LIST_MODULES_ALL)
        self.assertEqual(psapi.cb, ctypes.sizeof(wintypes.HMODULE * MAX_MODULES))
        self.assertEqual(found['codepage'], 936)
        overflow = FakePsapi(needed_extra=ctypes.sizeof(wintypes.HMODULE * MAX_MODULES))
        self.assertIsNone(read_target_nls_ansi_code_page(ImageMemory(image), psapi=overflow))

    def test_malformed_pe_bad_rva_ordinal_count_forwarder_and_unstable_read_fail_closed(self):
        image, value_rva, export_rva = build_image()
        cases = []
        broken = bytearray(image)
        broken[0:2] = b'NZ'
        cases.append(broken)
        broken = bytearray(image)
        broken[0x80:0x84] = b'NOPE'
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<H', broken, 0x84, 0x8664)
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<H', broken, 0x80 + 24, 0x20b)
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<I', broken, 0x80 + 24 + 96, 0x9000)
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<II', broken, export_rva + 20, 9000, 9000)
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<II', broken, export_rva + 20, 3, 5)
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<H', broken, 0x2C0 + 2, 99)
        cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<I', broken, 0x280 + 4, export_rva)
        cases.append(broken)
        for sample in cases:
            self.assertIsNone(read_target_nls_ansi_code_page(ImageMemory(sample), enumerate_modules=listed))
        mem = ImageMemory(image)
        mem.flip_on[BASE + value_rva] = 2
        self.assertIsNone(read_target_nls_ansi_code_page(mem, enumerate_modules=listed))

    def test_reader_exception_returns_none(self):
        class Boom:
            h = 1

            def read(self, address, size):
                raise OSError('unreadable')

        self.assertIsNone(read_target_nls_ansi_code_page(Boom(), enumerate_modules=listed))

    def test_undeclared_export_directory_and_unterminated_name_are_rejected(self):
        image, _, _ = build_image()
        cases = []
        for size in (0, 103, 65535):
            broken = bytearray(image)
            struct.pack_into('<H', broken, 0x80 + 20, size)
            cases.append(broken)
        broken = bytearray(image)
        struct.pack_into('<I', broken, 0x80 + 24 + 92, 0)
        cases.append(broken)
        broken = bytearray(image)
        name = b'NlsAnsiCodePage'
        rva = len(broken) - len(name)
        broken[rva:] = name
        struct.pack_into('<I', broken, 0x2A0 + 4, rva)
        cases.append(broken)
        for broken in cases:
            self.assertIsNone(read_target_nls_ansi_code_page(ImageMemory(broken), enumerate_modules=listed))

    def test_ambiguous_target_ntdll_modules_are_rejected(self):
        image, _, _ = build_image()
        first = ImageMemory(image)
        second = ImageMemory(build_image(1252)[0])
        second.base = BASE + 0x10000

        class Both:
            h = 1

            def read(self, address, size):
                return (second if address >= second.base else first).read(address, size)

        pair = [(BASE, PATH), (second.base, PATH)]
        for modules in (pair, list(reversed(pair))):
            self.assertIsNone(read_target_nls_ansi_code_page(Both(), enumerate_modules=lambda h: modules))
        same = read_target_nls_ansi_code_page(first, enumerate_modules=lambda h: [(BASE, PATH), (BASE, PATH)])
        self.assertEqual(same['codepage'], 936)

    def test_player_slots_follow_the_target_image_not_helper_1252(self):
        image, _, _ = build_image(936)
        image_mem = ImageMemory(image)

        class Combo:
            def __init__(self):
                self.h = image_mem.h
                self.slots = None

            def read(self, address, size):
                if BASE <= address < BASE + len(image_mem.image):
                    return image_mem.read(address, size)
                return self.slots.read(address, size)

        from test_player_slots import CORE, RAW, Sparse, plant_name, snapshot
        combo = Combo()
        combo.slots = Sparse()
        plant_name(combo.slots, 0, 182562834, 0, 7, RAW)
        calls = []

        def win_dll(name, use_last_error=True):
            calls.append(name.lower())
            if name.lower() == 'psapi':
                return FakePsapi()
            if name.lower() == 'kernel32':
                return type('Kernel', (), {'GetACP': lambda self: 1252})()
            raise OSError(name)

        with patch('target_codepage.ctypes.WinDLL', win_dll, create=True):
            view = player_slots.read_player_slots(combo, CORE, player_slots.VERIFIED_BUILD, [{'force_id': 7}])
        self.assertIn('psapi', calls)
        self.assertNotIn('kernel32', calls)
        self.assertEqual(view['player_slots'][0]['nickname'], '韩立(筑基后期)')
        self.assertEqual(view['player_slots'][0]['raw_hex'], RAW_NICK.hex())
        self.assertNotEqual(view['player_slots'][0]['nickname'], RAW_NICK.decode('cp1252'))
        self.assertEqual(view['layout']['ansi_code_page'], 936)
        self.assertEqual(view['layout']['ansi_code_page_source'], 'target_ntdll_NlsAnsiCodePage')
        self.assertTrue(view['layout']['target_ansi_code_page_directly_observed'])
        self.assertFalse(view['layout']['target_code_executed'])
        self.assertEqual(player_slots.display_nickname(snapshot(view), 7), '韩立(筑基后期)')


if __name__ == '__main__':
    unittest.main()
