"""P36 E2 loader client (runs under WIN32 python in Wine).

Reads config JSON from stdin, loads the ORIGINAL NetHookLoader.dll, points it
at a local fake relay (our own machine), then dumps self info + user table so
the fake relay's injected control messages become observable.

No game, no real relay, no other machines. Read-only w.r.t. game files.
"""
import ctypes as c
import hashlib
import json
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

ROOT = Path(r'C:\sgi\run-3.5')
LOADER_SHA = '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a'


def main():
    cfg = json.load(sys.stdin)
    loader = ROOT / 'NetHookLoader.dll'
    digest = hashlib.sha256(loader.read_bytes()).hexdigest()
    out = {'loader_sha256': digest, 'loader_sha_ok': digest == LOADER_SHA}
    if not out['loader_sha_ok']:
        print(json.dumps(out), flush=True)
        return
    cb_events = []
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(kind, data):
        cb_events.append([int(kind), int(data)])
        return 0

    dll = c.WinDLL(str(loader))
    dll.InitDll.argtypes = [CB, c.c_ushort]
    dll.InitDll.restype = c.c_int
    dll.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                                c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    dll.StartServer.restype = c.c_int
    dll.StopServer.argtypes = []
    dll.FinalDll.argtypes = []
    dll.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    dll.GetSelfUserIpInfo.restype = c.c_int
    dll.GetUserInfoAry.argtypes = [c.c_void_p, c.c_int]
    dll.GetUserInfoAry.restype = c.c_int

    u = c.WinDLL('user32')
    u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    msg = w.MSG()

    def pump():
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg))
            u.DispatchMessageW(c.byref(msg))

    out['init_rc'] = dll.InitDll(callback, int(cfg['local_port']))
    print(json.dumps(out), flush=True)
    if out['init_rc'] != 0:
        return
    out = {}
    out['start_rc'] = dll.StartServer(
        cfg['virtual_ip'].encode('ascii'), cfg['relay_ip'].encode('ascii'),
        int(cfg['relay_port']), str(ROOT / 'WS2.dll').encode('ascii'),
        int(cfg.get('game_id', 1001)), int(cfg.get('user_id', 12345)),
        cfg.get('username', 'p36tester').encode('gbk'),
        cfg.get('token', 't36').encode('gbk'))
    print(json.dumps({'start_rc': out['start_rc']}), flush=True)

    t0 = time.time()
    seconds = float(cfg.get('seconds', 30))
    ipbuf = c.create_string_buffer(16)
    dumped = False
    while time.time() - t0 < seconds:
        pump()
        time.sleep(0.1)
        self_rc = dll.GetSelfUserIpInfo(ipbuf)
        arr = c.create_string_buffer(0x3D * 32)
        n = dll.GetUserInfoAry(arr, 32)
        rows = [arr.raw[i * 0x3D:(i + 1) * 0x3D].hex() for i in range(max(0, min(n, 32)))]
        line = {'t': round(time.time() - t0, 2), 'self_rc': self_rc,
                'self_hex': ipbuf.raw.hex(), 'count': n, 'rows': rows,
                'events': cb_events[-4:]}
        if not dumped and time.time() - t0 > 3.5:
            dumped = True
            globals_read = {}
            try:
                k32 = c.WinDLL('kernel32')
                k32.GetModuleHandleA.argtypes = [c.c_char_p]
                k32.GetModuleHandleA.restype = c.c_void_p
                base = k32.GetModuleHandleA(b'NetHookLoader.dll')
                globals_read['loader_base'] = hex(base) if base else None
                if base:
                    for name, off, size in [('f104_thread', 0x3F104, 4),
                                            ('f108_thread', 0x3F108, 4),
                                            ('f11c_initport', 0x3F11C, 2),
                                            ('f124_sockA', 0x3F124, 4),
                                            ('f128_A8', 0x3F128, 4),
                                            ('f12c_Aport_raw', 0x3F12C, 2),
                                            ('f130_objB0', 0x3F130, 4),
                                            ('f134_sockB', 0x3F134, 4),
                                            ('f138_B8', 0x3F138, 4),
                                            ('f13c_Bport_raw', 0x3F13C, 2),
                                            ('f140_objC0', 0x3F140, 4),
                                            ('f144_sockC', 0x3F144, 4),
                                            ('f148_C8', 0x3F148, 4),
                                            ('f14c_Cport_raw', 0x3F14C, 2)]:
                        blob = c.string_at(base + off, size)
                        globals_read[name] = int.from_bytes(blob, 'little')
                    for nm, key in [('A', 'f12c_Aport_raw'), ('B', 'f13c_Bport_raw'),
                                    ('C', 'f14c_Cport_raw')]:
                        raw = globals_read.get(key, 0)
                        globals_read[nm + '_port'] = ((raw & 0xFF) << 8) | (raw >> 8)
                    for tobj_name, toff in [('threadA', 0x3F104), ('threadB', 0x3F108)]:
                        ptr = int.from_bytes(c.string_at(base + toff, 4), 'little')
                        if ptr:
                            globals_read[tobj_name + '_obj'] = hex(ptr)
                            globals_read[tobj_name + '_18'] = c.string_at(ptr + 0x18, 1)[0]
                            globals_read[tobj_name + '_19'] = c.string_at(ptr + 0x19, 1)[0]
                            globals_read[tobj_name + '_30'] = c.string_at(ptr + 0x30, 1)[0]
                            globals_read[tobj_name + '_34'] = int.from_bytes(c.string_at(ptr + 0x34, 4), 'little')
            except Exception as e:
                globals_read['error'] = str(e)
            line['globals'] = globals_read
        print(json.dumps(line), flush=True)
    try:
        dll.StopServer()
    except Exception:
        pass
    try:
        dll.FinalDll()
    except Exception:
        pass
    print(json.dumps({'state': 'exit_clean'}), flush=True)


if __name__ == '__main__':
    main()
