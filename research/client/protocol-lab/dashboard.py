"""Loopback-only room list. Polls the resident collector; never re-logins.

Prefer resident-status.json / resident HTTP. Does NOT spawn native_login_probe
(old path: 0x200b enter + 0x2002 logout every cycle — banned; abcde high-risk).
Exposes hall_presence / room_list_visible_expected from the resident status.
"""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INTERVAL = 2
RESIDENT_STATUS = Path(
    __import__("os").environ.get(
        "SGI_TK_RESIDENT_STATUS", str(ROOT / "resident-status.json")
    )
)
RESIDENT_HTTP = __import__("os").environ.get(
    "SGI_TK_RESIDENT_HTTP", "http://127.0.0.1:18774/api"
)
LOCK = threading.Lock()
STATE = {
    "phase": "idle",
    "account": "unconfigured",
    "rooms": [],
    "observed_at": None,
    "interval_seconds": INTERVAL,
    "next_query_at": None,
    "history": [],
    "error": None,
    "source": "resident",
    "game_start_confirmed": False,
    "hall_presence": None,
    "room_list_visible_expected": False,
    "presence_mechanism": None,
    "opensession_join": False,
}
last_view = 0


def _read_resident_file():
    if not RESIDENT_STATUS.is_file():
        return None
    try:
        return json.loads(RESIDENT_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_resident_http():
    try:
        with urllib.request.urlopen(RESIDENT_HTTP, timeout=2) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def read_resident():
    # Prefer HTTP when resident serves it; fall back to status file.
    return _read_resident_http() or _read_resident_file()


def collect():
    while True:
        now = time.time()
        with LOCK:
            viewing = last_view > now - 45
        if not viewing:
            time.sleep(1)
            continue
        row = read_resident()
        with LOCK:
            if not row:
                STATE.update(
                    phase="error",
                    error="常驻采集未运行：请先 start-resident，勿再整段登录进出",
                    next_query_at=None,
                )
            else:
                previous = STATE["rooms"]
                current = row.get("rooms") or []
                at = row.get("observed_at")
                status = row.get("query_status")
                phase = row.get("phase") or "ready"
                if phase in ("ready", "reconnecting", "establishing", "stopped"):
                    mapped = {
                        "ready": "ready",
                        "reconnecting": "error",
                        "establishing": "querying",
                        "stopped": "error",
                    }.get(phase, "ready")
                else:
                    mapped = "ready" if row.get("ok") else "error"
                if at is not None and (previous != current or STATE["observed_at"] is None):
                    if status == "unconfirmed_empty":
                        text = "本轮未收到房间回应（不能据此确认无房或已开局）"
                    else:
                        text = f"收到 {len(current)} 个房间" if current else "本轮未收到房间回应"
                    STATE["history"].insert(0, {"at": at, "rooms": current, "text": text})
                    STATE["history"] = STATE["history"][:20]
                err = row.get("error")
                if mapped == "error" and not err:
                    err = "常驻会话异常或已停止"
                STATE.update(
                    phase=mapped,
                    account=row.get("account", "unconfigured"),
                    rooms=current,
                    observed_at=at,
                    query_status=status,
                    error=err if mapped == "error" else None,
                    session_id=row.get("session_id"),
                    search_cycles=row.get("search_cycles"),
                    enter_count=row.get("enter_count"),
                    logout_count=row.get("logout_count"),
                    login_count=row.get("login_count"),
                    hall_presence=row.get("hall_presence"),
                    room_list_visible_expected=bool(
                        row.get("room_list_visible_expected")
                    ),
                    presence_mechanism=row.get("presence_mechanism"),
                    opensession_join=False,
                    game_start_confirmed=False,
                    source="resident",
                    next_query_at=now + INTERVAL,
                )
        time.sleep(INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global last_view
        if self.path == "/":
            body = (ROOT / "dashboard.html").read_bytes()
            kind = "text/html; charset=utf-8"
        elif self.path == "/api":
            with LOCK:
                last_view = time.time()
                body = json.dumps(STATE, ensure_ascii=False).encode()
            kind = "application/json; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=collect, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 18773), Handler).serve_forever()
