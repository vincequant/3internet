"""P2 loader host: StartServer on the probe's own grant, then spawn the
NetHookCore-hooked join child (mirrors the verified P1 architecture where the
child's transport hook routes traffic through the parent's relay).
"""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    assert Path(os.environ.get('WINEPREFIX', '')).name == 'prefix-monitor'
    assert c.sizeof(c.c_void_p) == 4
    cfg = json.load(sys.stdin)
    for key in ('username', 'virtual_ip', 'server', 'port', 'game_id', 'user_id', 'token',
                'search_target', 'session_name', 'hold_seconds'):
        assert cfg.get(key) is not None, f'missing {key}'
    root = Path(r'C:\sgi\run-3.5')
    hashes = {'NetHookLoader.dll': '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
              'WS2.dll': '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88'}
    for name, digest in hashes.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(kind, data):
        return 0

    loader = c.WinDLL(str(root/'NetHookLoader.dll'))
    loader.InitDll.argtypes = [CB, c.c_ushort]
    loader.InitDll.restype = c.c_int
    loader.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                                   c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    loader.StartServer.restype = c.c_int
    loader.StopServer.argtypes = []
    loader.FinalDll.argtypes = []
    loader.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    loader.GetSelfUserIpInfo.restype = c.c_int
    result = {'init_rc': loader.InitDll(callback, 4578)}
    if result['init_rc'] != 0:
        print(json.dumps(result))
        return
    u = c.WinDLL('user32')

    def pump():
        msg = None
        try:
            from ctypes import wintypes as w
            msg = w.MSG()
        except Exception:
            return

    k32 = c.WinDLL('kernel32')
    k32.GetModuleHandleA.argtypes = [c.c_char_p]
    k32.GetModuleHandleA.restype = c.c_void_p

    def read_globals():
        base = k32.GetModuleHandleA(b'NetHookLoader.dll')
        if not base:
            return {}
        def bswap16(raw):
            return ((raw & 0xFF) << 8) | (raw >> 8)
        out = {'loader_base': hex(base)}
        for name, off in (('f11c_initport', 0x3F11C), ('f12c_Araw', 0x3F12C),
                          ('f13c_Braw', 0x3F13C)):
            out[name] = int.from_bytes(c.string_at(base + off, 2), 'little')
        out['init_port'] = bswap16(out['f11c_initport'])
        out['a_port'] = bswap16(out['f12c_Araw'])
        out['b_port'] = bswap16(out['f13c_Braw'])
        return out

    def ctx_write_now():
        path = os.environ.get('P2_CTX_FILE')
        if not path:
            return
        payload = {'wall': time.time(), 'registered': result.get('relay_registered'),
                   'self_hex': result.get('self_hex'), 'child_pid': result.get('child_pid')}
        payload.update(read_globals())
        try:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except OSError:
            pass

    try:
        result['start_rc'] = loader.StartServer(cfg['virtual_ip'].encode('ascii'),
            cfg['server'].encode('ascii'), cfg['port'], str(root/'WS2.dll').encode('ascii'),
            cfg['game_id'], cfg['user_id'], cfg['username'].encode('gbk'), cfg['token'].encode('gbk'))
        ip_info = c.create_string_buffer(16)
        until = time.monotonic()+5
        while time.monotonic() < until:
            time.sleep(0.02)
            if loader.GetSelfUserIpInfo(ip_info) == 0:
                break
        result['relay_registered'] = loader.GetSelfUserIpInfo(ip_info) == 0
        result['self_hex'] = ip_info.raw.hex()
        ctx_write_now()
        err_path = os.environ.get('P2_CHILD_STDERR')
        err_target = open(err_path, 'wb') if err_path else subprocess.PIPE
        child_script = os.environ.get('P2_CHILD_SCRIPT', 'p2_join_probe.py')
        child_args_json = os.environ.get('P2_CHILD_ARGS_JSON')
        child_extra = (json.loads(child_args_json) if child_args_json
                       else os.environ.get('P2_CHILD_ARGS', '').split())
        if not isinstance(child_extra, list) or not all(isinstance(a, str) for a in child_extra):
            raise ValueError('P2_CHILD_ARGS_JSON must be a list of strings')
        child_argv = [sys.executable, '-X', 'utf8',
            str(Path(__file__).with_name(child_script)),
            '--target', cfg['search_target'], '--session-name', cfg['session_name'],
            '--username', cfg['username'], '--hold', str(cfg['hold_seconds'])] + child_extra
        result['child_script'] = child_script
        child = subprocess.Popen(child_argv,
            stdout=subprocess.PIPE, stderr=err_target, text=True)
        result['child_pid'] = child.pid
        ctx_write_now()
        out, err = child.communicate(timeout=cfg['hold_seconds'] + 120)
        result['child_exit'] = child.returncode
        result['child'] = [json.loads(x) for x in out.splitlines() if x.startswith('{')]
        result['child_stderr_tail'] = (err or '').strip()[-300:]
    finally:
        try:
            loader.StopServer()
            loader.FinalDll()
        except Exception:
            pass
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__}))
        sys.exit(1)
