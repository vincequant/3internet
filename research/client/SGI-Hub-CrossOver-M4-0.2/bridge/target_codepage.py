"""Read target ntdll!NlsAnsiCodePage without executing target code.

The value is a USHORT in the target process. EnumProcessModulesEx and
GetModuleFileNameExW run in the collector. Nothing calls target GetACP.
"""
import codecs
import ctypes
from ctypes import wintypes
import struct

LIST_MODULES_ALL = 3
MAX_MODULES = 1024
MAX_READ = 4096
MAX_EXPORTS = 8192
MAX_NAME = 64
USER_LOW = 0x10000
USER_HIGH = 0x80000000
MACHINE_I386 = 0x14c
PE32 = 0x10b
EXPORT_NAME = b'NlsAnsiCodePage'


def _codec(codepage):
    if type(codepage) is not int or not 0 < codepage <= 65535:
        return None
    try:
        codecs.lookup('cp%d' % codepage)
    except LookupError:
        return None
    return codepage


def _read_abs(memory, address, size):
    if type(address) is not int or type(size) is not int:
        return None
    if size <= 0 or size > MAX_READ:
        return None
    if address < USER_LOW or address >= USER_HIGH or size > USER_HIGH - address:
        return None
    try:
        data = memory.read(address, size)
    except Exception:
        return None
    if isinstance(data, bool) or not isinstance(data, (bytes, bytearray, memoryview)):
        return None
    raw = bytes(data)
    if len(raw) != size:
        return None
    return raw


def _read_rva(memory, base, image_size, rva, size):
    if type(base) is not int or type(image_size) is not int or type(rva) is not int:
        return None
    if image_size <= 0 or base < USER_LOW or image_size > USER_HIGH - base:
        return None
    if rva < 0 or rva >= image_size or size > image_size - rva:
        return None
    return _read_abs(memory, base + rva, size)


def _declare(func, argtypes, restype):
    try:
        func.argtypes = argtypes
        func.restype = restype
    except (AttributeError, TypeError):
        return None


def _enumerate_with_psapi(handle, psapi=None):
    if not handle:
        return None
    try:
        if psapi is None:
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            _declare(psapi.EnumProcessModulesEx, [
                wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD), wintypes.DWORD], wintypes.BOOL)
            _declare(psapi.GetModuleFileNameExW, [
                wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD)
        modules = (wintypes.HMODULE * MAX_MODULES)()
        needed = wintypes.DWORD(0)
        size = ctypes.sizeof(modules)
        ok = psapi.EnumProcessModulesEx(handle, modules, size, ctypes.byref(needed), LIST_MODULES_ALL)
    except (OSError, AttributeError, TypeError, ValueError):
        return None
    if not ok:
        return None
    width = ctypes.sizeof(wintypes.HMODULE)
    if needed.value <= 0 or needed.value > size or needed.value % width:
        return None
    count = needed.value // width
    if count <= 0 or count > MAX_MODULES:
        return None
    found = []
    for index in range(count):
        try:
            base = int(modules[index])
        except (TypeError, ValueError):
            continue
        if not USER_LOW <= base < USER_HIGH:
            continue
        path = _module_path(psapi, handle, modules[index])
        if path:
            found.append((base, path))
    return found


def _module_path(psapi, handle, module):
    buffer = ctypes.create_unicode_buffer(1024)
    try:
        written = int(psapi.GetModuleFileNameExW(handle, module, buffer, len(buffer)) or 0)
    except (OSError, AttributeError, TypeError, ValueError):
        return None
    if written <= 0 or written >= len(buffer):
        return None
    return buffer.value


def _pe32_export(memory, base):
    dos = _read_abs(memory, base, 0x40)
    if dos is None or dos[:2] != b'MZ':
        return None
    e_lfanew = struct.unpack_from('<I', dos, 0x3c)[0]
    if not 0 < e_lfanew < MAX_READ:
        return None
    header = _read_abs(memory, base + e_lfanew, 256)
    if header is None or header[:4] != b'PE\0\0':
        return None
    if struct.unpack_from('<H', header, 4)[0] != MACHINE_I386:
        return None
    optional_size = struct.unpack_from('<H', header, 20)[0]
    if optional_size < 104:
        return None
    if struct.unpack_from('<H', header, 24)[0] != PE32:
        return None
    if struct.unpack_from('<I', header, 24 + 92)[0] < 1:
        return None
    image_size = struct.unpack_from('<I', header, 24 + 56)[0]
    if image_size <= e_lfanew + 256 or image_size > USER_HIGH - base:
        return None
    if optional_size > image_size - e_lfanew - 24:
        return None
    export_rva, export_size = struct.unpack_from('<II', header, 24 + 96)
    if export_size < 40 or export_rva <= 0 or export_rva > image_size - export_size:
        return None
    directory = _read_rva(memory, base, image_size, export_rva, 40)
    if directory is None:
        return None
    functions, names, function_table, name_table, ordinal_table = struct.unpack_from('<5I', directory, 20)
    if not 0 < names <= functions <= MAX_EXPORTS:
        return None
    if function_table <= 0 or name_table <= 0 or ordinal_table <= 0:
        return None
    if function_table > image_size - functions * 4:
        return None
    if name_table > image_size - names * 4 or ordinal_table > image_size - names * 2:
        return None
    low, high = 0, names - 1
    found = None
    while low <= high:
        index = (low + high) // 2
        name_rva_bytes = _read_rva(memory, base, image_size, name_table + 4 * index, 4)
        if name_rva_bytes is None:
            return None
        name_rva = struct.unpack('<I', name_rva_bytes)[0]
        if name_rva <= 0 or name_rva >= image_size:
            return None
        raw = _read_rva(memory, base, image_size, name_rva, min(MAX_NAME, image_size - name_rva))
        if raw is None:
            return None
        if b'\0' not in raw:
            return None
        raw_name = raw.split(b'\0', 1)[0]
        if raw_name < EXPORT_NAME:
            low = index + 1
        elif raw_name > EXPORT_NAME:
            high = index - 1
        else:
            found = index
            break
    if found is None:
        return None
    ordinal_bytes = _read_rva(memory, base, image_size, ordinal_table + 2 * found, 2)
    if ordinal_bytes is None:
        return None
    ordinal = struct.unpack('<H', ordinal_bytes)[0]
    if ordinal >= functions:
        return None
    value_rva_bytes = _read_rva(memory, base, image_size, function_table + 4 * ordinal, 4)
    if value_rva_bytes is None:
        return None
    value_rva = struct.unpack('<I', value_rva_bytes)[0]
    if export_rva <= value_rva < export_rva + export_size:
        return None
    if value_rva <= 0 or value_rva > image_size - 2:
        return None
    first = _read_rva(memory, base, image_size, value_rva, 2)
    second = _read_rva(memory, base, image_size, value_rva, 2)
    if first is None or first != second:
        return None
    codepage = _codec(struct.unpack('<H', first)[0])
    if codepage is None:
        return None
    return {
        'codepage': codepage,
        'module_base': base,
        'export_rva': value_rva,
        'raw': first,
        'raw_hex': first.hex(),
        'double_read': True,
        'read_only': True,
        'target_code_executed': False,
        'source': 'target_ntdll_NlsAnsiCodePage',
        'observation': 'ReadProcessMemory of target ntdll!NlsAnsiCodePage',
    }


def _read_target(memory, enumerate_modules, psapi):
    handle = getattr(memory, 'h', None)
    if not handle:
        return None
    if enumerate_modules is None:
        modules = _enumerate_with_psapi(handle, psapi)
    else:
        modules = enumerate_modules(handle)
    if not isinstance(modules, list) or not modules or len(modules) > MAX_MODULES:
        return None
    candidates = {}
    for item in modules:
        if not isinstance(item, tuple) or len(item) != 2:
            return None
        base, path = item
        if type(base) is not int or type(path) is not str or not path.lower().endswith('\\ntdll.dll'):
            continue
        found = _pe32_export(memory, base)
        if found is None:
            continue
        found['module_path'] = path
        candidates[base] = found
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def read_target_nls_ansi_code_page(memory, enumerate_modules=None, psapi=None):
    """Return the target code page evidence, or None. Never raises."""
    try:
        return _read_target(memory, enumerate_modules, psapi)
    except Exception:
        return None
