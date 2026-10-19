"""Bounded native-vs-Python checksum test on owned buffers/files; no network."""
import ctypes as c
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p30_ready import checksum

root = Path(r'C:\sgi\run-3.5\3I')
path = root/'Koeitlbm.dll'
assert hashlib.sha256(path.read_bytes()).hexdigest() == 'd3415eb8c615e88eb7a609f713064f0d5b71b8f8a9ba0cdf2056e02faec360fa'
dll = c.CDLL(str(path))  # cdecl, source ends plain RET; caller cleans two args
dll.Func0503.argtypes, dll.Func0503.restype = [], None
dll.Func0504.argtypes, dll.Func0504.restype = [c.c_void_p, c.c_int], c.c_uint32
dll.Func0503()
result = []
inputs = [('empty', b''), ('standard_check', b'123456789'), ('byte_range', bytes(range(256)))]
inputs += [(p.name, p.read_bytes()) for p in (root/'snr').iterdir()
           if p.name.lower().startswith('sndata') and p.suffix.lower() == '.s6i']
for name, data in inputs:
    assert len(data) < 2*1024*1024
    buffer = c.create_string_buffer(data)
    native = dll.Func0504(buffer, len(data))
    actual = checksum(data)
    assert native == actual, (name, native, actual)
    result.append({'name': name, 'sha256': hashlib.sha256(data).hexdigest(),
                   'length': len(data), 'native': native, 'python': actual})
assert result[1]['native'] == 0x906e
Path(sys.argv[1]).write_text(json.dumps({'passed': True, 'no_network': True,
    'native_dll_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'cases': result}, indent=2), encoding='utf-8')
