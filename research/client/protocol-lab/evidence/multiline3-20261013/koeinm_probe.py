"""Bounded standalone 32-bit DLL experiment; no game process access.

The loopback fixture is synthetic and MUST NOT be reported as a live room.
Other modes send one normal search to an explicit user-controlled endpoint.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time

EXPECTED = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', required=True)
    ap.add_argument('--target', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=0)
    ap.add_argument('--app-id', type=lambda x: int(x, 0), default=0x534749)
    ap.add_argument('--loopback-fixture', action='store_true')
    ap.add_argument('--with-nethook', action='store_true', help='Load original transport DLL into this probe only')
    args = ap.parse_args()
    assert c.sizeof(c.c_void_p) == 4, 'Requires Win32 Python'
    dllpath = Path(args.dll).resolve()
    assert hashlib.sha256(dllpath.read_bytes()).hexdigest() == EXPECTED
    if not args.loopback_fixture and not 0 < args.port < 65536:
        ap.error('Non-fixture mode requires an explicit port')
    result = {'synthetic': args.loopback_fixture, 'dll_sha256': EXPECTED,
              'rooms': [], 'request_hex': None, 'process': 'standalone_python32'}
    result['windows_version'] = list(sys.getwindowsversion())
    fixture = None
    if args.loopback_fixture:
        assert args.target == '127.0.0.1'
        fixture = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        fixture.bind(('127.0.0.1', 0))
        fixture.settimeout(8)
        args.port = fixture.getsockname()[1]

        def serve():
            try:
                raw, peer = fixture.recvfrom(128)
                result['request_hex'] = raw.hex()
                if raw != struct.pack('!I', args.app_id):
                    result['fixture_error'] = 'Unexpected request'
                    return
                response = (struct.pack('!I', 123) + b'LOCAL_FIXTURE'.ljust(31, b'\0')
                            + b'SYNTHETIC'.ljust(31, b'\0') + struct.pack('!III', 8, 3, 0xb9d9))
                fixture.sendto(response, peer)
            except Exception as exc:
                result['fixture_error'] = str(exc)
            finally:
                fixture.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

    u = c.WinDLL('user32', use_last_error=True)
    k = c.WinDLL('kernel32', use_last_error=True)
    # PostMessageA(NULL, ...) targets the calling thread's message queue.
    # SearchSession has no dependency on a visible game window.
    u.PeekMessageA.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.PeekMessageA.restype = w.BOOL
    k.GlobalFree.argtypes = [w.HGLOBAL]
    k.GlobalFree.restype = w.HGLOBAL
    message = w.MSG()
    u.PeekMessageA(c.byref(message), None, 0, 0, 0)
    hwnd = None
    dll = c.WinDLL(str(dllpath))
    if args.with_nethook:
        assert not args.loopback_fixture
        hookpath = dllpath.parent.parent / 'NetHookCore.dll'
        hook_hash = hashlib.sha256(hookpath.read_bytes()).hexdigest()
        assert hook_hash == '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'
        print(json.dumps({'stage': 'loading_transport', 'sha256': hook_hash}), flush=True)
        hook = c.WinDLL(str(hookpath))
        result['transport_loaded'] = bool(hook._handle)
    start = getattr(dll, '_NetMsg_Start@36')
    start.argtypes = [c.c_uint32] * 8 + [c.POINTER(c.c_uint32)]
    start.restype = c.c_int
    search = getattr(dll, '_NetMsg_SearchSession@12')
    search.argtypes = [c.c_char_p, w.HWND, w.UINT]
    search.restype = c.c_int
    end = getattr(dll, '_NetMsg_End@0')
    end.argtypes = []
    end.restype = c.c_int
    network_flag = c.c_uint32()
    started = time.monotonic()
    result['start_rc'] = start(8, 64, args.port, 100, 100, args.app_id, 0, 0, c.byref(network_flag))
    print(json.dumps({'stage': 'initialized', 'return_code': result['start_rc']}), flush=True)
    if result['start_rc'] == 0:
        try:
            result['search_rc'] = search(args.target.encode('ascii'), hwnd, 0x2403)
            while u.PeekMessageA(c.byref(message), None, 0x2403, 0x2403, 1):
                if message.wParam != 5 or not message.lParam:
                    continue
                ptr = c.c_void_p(message.lParam)
                raw = c.string_at(ptr, 80)
                result['rooms'].append({
                    'id': str(struct.unpack_from('<I', raw, 0)[0]),
                    'name': raw[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                    'host': raw[35:66].split(b'\0')[0].decode('gbk', 'replace'),
                    'maximum': struct.unpack_from('<I', raw, 68)[0],
                    'current': struct.unpack_from('<I', raw, 72)[0],
                    'version': struct.unpack_from('<I', raw, 76)[0],
                })
                k.GlobalFree(ptr)
        finally:
            result['end_rc'] = end()
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    result['reply_count'] = len(result['rooms'])
    # The relay can return the same room through multiple network routes.
    result['rooms'] = list({(r['id'], r['name'], r['host']): r for r in result['rooms']}.values())
    result['observed_at'] = time.time()
    result['query_status'] = 'replies_received' if result['rooms'] else 'unconfirmed_empty'
    result['credentials_only_verified'] = False
    if args.loopback_fixture:
        thread.join(0.5)
        result['fixture_pass'] = (result.get('search_rc') == 0 and result['request_hex'] == struct.pack('!I', args.app_id).hex()
                                  and len(result['rooms']) == 1 and result['rooms'][0]['current'] == 3)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
