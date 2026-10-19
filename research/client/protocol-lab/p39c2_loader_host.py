# -*- coding: utf-8 -*-
"""P39c2 loader host (Wine, prefix-monitor): relay registration + dumps.

Based on the proven p2_loader_host.py (StartServer relay registration; the
child's transport hook routes through this parent's relay) and the
p36_loader_client.py globals read. Adds two evidence-side dumps:

  P39C2_CTX_FILE  -- atomic JSON {wall, init_port, a_port, b_port,
                    loader_base, relay_registered, self_hex} rewritten
                    every ~2 s (the Mac orchestrator reads the B port to
                    send the single 1000 instruction from the Mac side,
                    exactly like the P36-E2 bed did).
  P39C2_TABLE_LOG -- append JSONL: the relay-fed user table (GetUserInfoAry)
                    decoded best-effort, one line per ~2 s. Read-only.

Child plumbing keeps the P2_CHILD_* env names so the verified E3 child
(p36e3_nonmember_probe.py) runs unchanged:
  P2_CHILD_SCRIPT, P2_CHILD_ARGS_JSON, P2_CHILD_STDERR.

Safety: read-only w.r.t. loader state; no game process access; no writes to
any remote; exactly the same StartServer call already proven in E1-E3.
"""
import ctypes as c
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

ROOT = Path(r'C:\sgi\run-3.5')
HASHES = {'NetHookLoader.dll':
          '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
          'WS2.dll':
          '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88'}
REC_SIZE = 0x3D


def bswap16(raw):
    return ((raw & 0xFF) << 8) | (raw >> 8)


def ctx_write(path, payload):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def decode_row(raw):
    """61B loader table row -> best-effort dict (id BE, per real wire/memory)."""
    def ip(b):
        return '.'.join(str(x) for x in b)
    try:
        return {
            'id': int.from_bytes(raw[0:4], 'big'),
            'ip_a': ip(raw[4:8]), 'port_a': int.from_bytes(raw[8:10], 'big'),
            'ip_b': ip(raw[10:14]), 'port_b': int.from_bytes(raw[14:16], 'big'),
            'state': raw[16], 'b17': raw[17], 'b23': raw[23],
            'raw_hex': raw.hex(),
        }
    except Exception as error:  # noqa: BLE001 - keep raw on any decode oddity
        return {'decode_error': type(error).__name__, 'raw_hex': raw.hex()}


def main():
    assert Path(os.environ.get('WINEPREFIX', '')).name == 'prefix-monitor'
    assert c.sizeof(c.c_void_p) == 4
    cfg = json.load(sys.stdin)
    for key in ('username', 'virtual_ip', 'server', 'port', 'game_id', 'user_id',
                'token', 'search_target', 'session_name', 'hold_seconds'):
        assert cfg.get(key) is not None, f'missing {key}'
    for name, digest in HASHES.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    ctx_path = Path(os.environ.get('P39C2_CTX_FILE', ''))
    table_path = Path(os.environ.get('P39C2_TABLE_LOG', ''))
    assert ctx_path.name and table_path.name, 'P39C2_CTX_FILE/P39C2_TABLE_LOG required'
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    result = {'kind': 'p39c2_loader_host', 'wall': time.time(),
              'mode': 'relay_registration_dumps_only'}
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(kind, data):
        return 0

    loader = c.WinDLL(str(ROOT / 'NetHookLoader.dll'))
    loader.InitDll.argtypes = [CB, c.c_ushort]
    loader.InitDll.restype = c.c_int
    loader.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                                   c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    loader.StartServer.restype = c.c_int
    loader.StopServer.argtypes = []
    loader.FinalDll.argtypes = []
    loader.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    loader.GetSelfUserIpInfo.restype = c.c_int
    loader.GetUserInfoAry.argtypes = [c.c_void_p, c.c_int]
    loader.GetUserInfoAry.restype = c.c_int
    u = c.WinDLL('user32')
    u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    msg = w.MSG()
    k32 = c.WinDLL('kernel32')
    k32.GetModuleHandleA.argtypes = [c.c_char_p]
    k32.GetModuleHandleA.restype = c.c_void_p

    def pump():
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg))
            u.DispatchMessageW(c.byref(msg))

    def read_globals():
        base = k32.GetModuleHandleA(b'NetHookLoader.dll')
        if not base:
            return {}
        out = {'loader_base': hex(base)}
        for name, off in (('f11c_initport', 0x3F11C), ('f12c_Araw', 0x3F12C),
                          ('f13c_Braw', 0x3F13C)):
            out[name] = int.from_bytes(c.string_at(base + off, 2), 'little')
        out['init_port'] = bswap16(out['f11c_initport'])
        out['a_port'] = bswap16(out['f12c_Araw'])
        out['b_port'] = bswap16(out['f13c_Braw'])
        return out

    result['init_rc'] = loader.InitDll(callback, 4578)
    if result['init_rc'] != 0:
        print(json.dumps(result, ensure_ascii=True))
        return
    child = None
    table_fh = table_path.open('a', encoding='utf-8')
    try:
        result['start_rc'] = loader.StartServer(
            cfg['virtual_ip'].encode('ascii'), cfg['server'].encode('ascii'),
            cfg['port'], str(ROOT / 'WS2.dll').encode('ascii'),
            cfg['game_id'], cfg['user_id'],
            cfg['username'].encode('gbk'), cfg['token'].encode('gbk'))
        ip_info = c.create_string_buffer(16)
        until = time.monotonic() + 8
        registered = False
        while time.monotonic() < until:
            pump()
            time.sleep(0.05)
            if loader.GetSelfUserIpInfo(ip_info) == 0:
                registered = True
                break
        result['relay_registered'] = registered
        result['self_hex'] = ip_info.raw.hex()
        glob = read_globals()
        result['globals'] = glob
        result['ctx_first'] = {
            'wall': time.time(), 'registered': registered,
            'init_port': glob.get('init_port'), 'a_port': glob.get('a_port'),
            'b_port': glob.get('b_port'), 'loader_base': glob.get('loader_base'),
            'self_hex': result['self_hex'], 'child_pid': None}
        ctx_write(ctx_path, result['ctx_first'])

        err_path = os.environ.get('P2_CHILD_STDERR')
        err_target = open(err_path, 'wb') if err_path else subprocess.PIPE
        child_script = os.environ.get('P2_CHILD_SCRIPT', 'p36e3_nonmember_probe.py')
        child_args_json = os.environ.get('P2_CHILD_ARGS_JSON')
        child_extra = (json.loads(child_args_json) if child_args_json
                       else os.environ.get('P2_CHILD_ARGS', '').split())
        if not isinstance(child_extra, list) or not all(isinstance(a, str) for a in child_extra):
            raise ValueError('P2_CHILD_ARGS_JSON must be a list of strings')
        child_argv = [sys.executable, '-X', 'utf8',
                      str(Path(__file__).with_name(child_script)),
                      '--target', cfg['search_target'],
                      '--session-name', cfg['session_name'],
                      '--username', cfg['username'],
                      '--hold', str(cfg['hold_seconds'])] + child_extra
        result['child_script'] = child_script
        child = subprocess.Popen(child_argv, stdout=subprocess.PIPE,
                                 stderr=err_target, text=True)
        result['child_pid'] = child.pid
        hold_deadline = time.monotonic() + cfg['hold_seconds'] + 180
        next_ctx = time.monotonic()
        next_tab = time.monotonic()
        dumps = 0
        while child.poll() is None and time.monotonic() < hold_deadline:
            pump()
            now = time.monotonic()
            if now >= next_ctx:
                next_ctx = now + 2.0
                glob = read_globals()
                ctx_write(ctx_path, {
                    'wall': time.time(), 'registered': registered,
                    'init_port': glob.get('init_port'), 'a_port': glob.get('a_port'),
                    'b_port': glob.get('b_port'),
                    'loader_base': glob.get('loader_base'),
                    'self_hex': result['self_hex'], 'child_pid': child.pid})
            if now >= next_tab:
                next_tab = now + 2.0
                buf = c.create_string_buffer(REC_SIZE * 32)
                n = loader.GetUserInfoAry(buf, 32)
                rows = []
                for i in range(max(0, min(int(n), 32))):
                    raw = buf.raw[i * REC_SIZE:(i + 1) * REC_SIZE]
                    rows.append(decode_row(raw))
                table_fh.write(json.dumps(
                    {'wall': time.time(), 'count': int(n), 'rows': rows},
                    ensure_ascii=False) + '\n')
                table_fh.flush()
                dumps += 1
            time.sleep(0.1)
        if child.poll() is None:
            result['child_timeout'] = True
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        out, err = child.communicate(timeout=30)
        result['child_exit'] = child.returncode
        result['child_stdout_lines'] = [x for x in (out or '').splitlines() if x.strip()][-5:]
        result['child_stderr_tail'] = (err or '').strip()[-300:] if err else ''
        result['table_dumps'] = dumps
    finally:
        try:
            loader.StopServer()
            loader.FinalDll()
        except Exception:  # noqa: BLE001 - keep exit clean
            pass
        table_fh.close()
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 - single-line failure contract
        print(json.dumps({'error_type': type(error).__name__,
                          'detail': str(error)[:300]}, ensure_ascii=True))
        sys.exit(1)
