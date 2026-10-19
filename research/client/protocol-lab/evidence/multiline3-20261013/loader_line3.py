"""Long-lived Wine relay: StartServer once, search on stdin commands, quit on demand.

Runs under Win32 Python inside prefix-monitor only. Grant arrives on stdin as one
JSON line (relay config), then command lines: {"cmd":"search"} / {"cmd":"quit"}.
Search uses koeinm_probe SearchSession (UDP) — no OpenSession join into SANPK
player slots (see evidence/alternate-observer-paths raw_nonjoining_search).
Never prints tokens or passwords. Refuses username abcde.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _pump(u, msg):
    while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
        u.TranslateMessage(c.byref(msg))
        u.DispatchMessageW(c.byref(msg))


def _one_search(root, python_exe):
    proc = subprocess.Popen(
        [
            python_exe,
            "-X",
            "utf8",
            str(Path(__file__).with_name("koeinm_probe.py")),
            "--dll",
            str(root / "3I/Koeinm.dll"),
            "--target",
            "255.255.255.255",
            "--port",
            "7777",
            "--app-id",
            "78731",
            "--with-nethook",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc


def main():
    # Accept AI Mac (/Users/vk/...) or COM (/Users/vkquant/...) as long as
    # the prefix directory name is prefix-monitor.
    _wp = Path(os.environ.get("WINEPREFIX") or "")
    assert _wp.name == "prefix-monitor" and _wp.is_dir()
    assert c.sizeof(c.c_void_p) == 4
    cfg = json.loads(sys.stdin.readline())
    # Refuse high-risk alt; live grant must come from a clean account.
    assert cfg.get("username") and cfg["username"] != "abcde"
    assert cfg["username"] not in ("abcde",)
    assert cfg["game_id"] == 1001 and cfg["room_id"] == 1002
    root = Path(r"C:\sgi\run-3.5")
    hashes = {
        "NetHookLoader.dll": "11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a",
        "WS2.dll": "79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88",
    }
    for name, digest in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest

    callback_events = []
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(kind, data):
        callback_events.append(1)
        return 0

    dll = c.WinDLL(str(root / "NetHookLoader.dll"))
    dll.InitDll.argtypes = [CB, c.c_ushort]
    dll.InitDll.restype = c.c_int
    dll.StartServer.argtypes = [
        c.c_char_p,
        c.c_char_p,
        c.c_int,
        c.c_char_p,
        c.c_uint32,
        c.c_uint32,
        c.c_char_p,
        c.c_char_p,
    ]
    dll.StartServer.restype = c.c_int
    dll.StopServer.argtypes = []
    dll.FinalDll.argtypes = []
    dll.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    dll.GetSelfUserIpInfo.restype = c.c_int

    result = {"init_rc": dll.InitDll(callback, 4578), "uses_original_relay_dll": True}
    if result["init_rc"] != 0:
        print(json.dumps({"stage": "init_failed", "init_rc": result["init_rc"]}), flush=True)
        return

    u = c.WinDLL("user32")
    u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    msg = w.MSG()

    try:
        result["start_rc"] = dll.StartServer(
            cfg["virtual_ip"].encode("ascii"),
            cfg["server"].encode("ascii"),
            cfg["port"],
            str(root / "WS2.dll").encode("ascii"),
            cfg["game_id"],
            cfg["user_id"],
            cfg["username"].encode("gbk"),
            cfg["token"].encode("gbk"),
        )
        del cfg
        ip_info = c.create_string_buffer(16)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            _pump(u, msg)
            time.sleep(0.02)
            if dll.GetSelfUserIpInfo(ip_info) == 0:
                break
        registered = dll.GetSelfUserIpInfo(ip_info) == 0
        print(
            json.dumps(
                {
                    "stage": "ready",
                    "start_rc": result["start_rc"],
                    "relay_registered": registered,
                }
            ),
            flush=True,
        )
        if not registered:
            return

        python_exe = sys.executable
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                print(json.dumps({"stage": "bad_command"}), flush=True)
                continue
            cmd = req.get("cmd")
            if cmd == "quit":
                print(json.dumps({"stage": "quitting"}), flush=True)
                break
            if cmd != "search":
                print(json.dumps({"stage": "unknown_command"}), flush=True)
                continue
            proc = _one_search(root, python_exe)
            deadline = time.monotonic() + 5
            while proc.poll() is None and time.monotonic() < deadline:
                _pump(u, msg)
                time.sleep(0.02)
            if proc.poll() is None:
                proc.kill()
            out, _err = proc.communicate()
            rooms = {}
            for raw in out.splitlines():
                if not raw.startswith("{"):
                    continue
                row = json.loads(raw)
                for room in row.get("rooms") or []:
                    rooms[(room.get("id"), room.get("name"), room.get("host"))] = room
            room_list = list(rooms.values())
            print(
                json.dumps(
                    {
                        "stage": "search_done",
                        "exit": proc.returncode,
                        "rooms": room_list,
                        "query_status": (
                            "replies_received" if room_list else "unconfirmed_empty"
                        ),
                        "callback_count": len(callback_events),
                        "observed_at": time.time(),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
    finally:
        try:
            dll.StopServer()
            dll.FinalDll()
        except Exception:
            pass
        print(json.dumps({"stage": "stopped"}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error_type": type(e).__name__, "stage": "error"}), flush=True)
        sys.exit(1)
