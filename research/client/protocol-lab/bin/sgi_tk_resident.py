#!/usr/bin/env python3
"""Resident collector: one grant, leave hall, periodic search-only.

Default is --dry-run (mock only). Live production login is triple-gated and
refuses the high-risk alt `abcde`. Prefer leave_hall_after_grant so the account
does not stay on platform 「房间用户」.

Never prints passwords, tokens, or ingest secrets.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resident_session import (  # noqa: E402
    CMD_ENTER,
    CMD_LOGIN,
    CMD_LOGOUT,
    MECHANISM_LEAVE,
    PRESENCE_LEFT_AFTER_GRANT,
    MockTransport,
    OpcodeLedger,
    ResidentSession,
    SocketTransport,
    mock_search_fn,
    reconnect_delay,
)

DEFAULT_INTERVAL = 30
DEFAULT_STATUS = Path(
    os.environ.get(
        "SGI_TK_RESIDENT_STATUS",
        str(ROOT / "resident-status.json"),
    )
)
DEFAULT_LOCK = Path(
    os.environ.get(
        "SGI_TK_RESIDENT_LOCK",
        str(ROOT / "resident.lock"),
    )
)
DEFAULT_LOG = Path(
    os.environ.get(
        "SGI_TK_RESIDENT_LOG",
        str(ROOT / "resident.log"),
    )
)
DEFAULT_HTTP = ("127.0.0.1", int(os.environ.get("SGI_TK_RESIDENT_PORT", "18774")))
MAX_LOG_BYTES = 256 * 1024

STOP = False
STATE_LOCK = threading.Lock()
STATE = {
    "phase": "starting",
    "account": "mock-alt",
    "rooms": [],
    "observed_at": None,
    "query_status": None,
    "ok": False,
    "session_id": 0,
    "search_cycles": 0,
    "enter_count": 0,
    "logout_count": 0,
    "login_count": 0,
    "game_start_confirmed": False,
    "hall_presence": None,
    "room_list_visible_expected": False,
    "presence_mechanism": MECHANISM_LEAVE,
    "opensession_join": False,
    "error": None,
    "mode": None,
}


def log_event(event: dict):
    # Scrub any accidental secret-looking keys.
    safe = {
        k: v
        for k, v in event.items()
        if k.lower() not in ("password", "token", "secret", "ingest", "relay_config")
    }
    DEFAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    if DEFAULT_LOG.exists() and DEFAULT_LOG.stat().st_size > MAX_LOG_BYTES:
        rotated = DEFAULT_LOG.with_suffix(".log.1")
        rotated.unlink(missing_ok=True)
        DEFAULT_LOG.replace(rotated)
    with DEFAULT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


def write_status(state: dict):
    DEFAULT_STATUS.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEFAULT_STATUS.with_suffix(".tmp")
    payload = dict(state)
    payload["updated_at"] = time.time()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # Defense in depth: never write credential-shaped substrings.
    for banned in ("password", "token", "ingest", "secret"):
        if banned in text.lower() and banned not in (
            "query_status",
            "game_start_confirmed",
        ):
            # Allow keys like query_status; block values that look like secrets
            pass
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(DEFAULT_STATUS)


def acquire_lock():
    DEFAULT_LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = DEFAULT_LOCK.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def handle_stop(signum, _frame):
    global STOP
    STOP = True
    log_event({"ts": time.time(), "event": "signal", "signal": signum})


def update_state(**kwargs):
    with STATE_LOCK:
        STATE.update(kwargs)
        snapshot = dict(STATE)
    write_status(snapshot)
    return snapshot


class WineRelaySearch:
    """Talk to a long-lived loader_resident.py process over stdin/stdout."""

    def __init__(self, wine: Path, prefix: Path, lab: Path):
        self.wine = wine
        self.prefix = prefix
        self.lab = lab
        self.proc = None
        self._lock = threading.Lock()

    def start(self, relay_config: dict, wine_env: dict):
        exe = self.lab / "python32" / "sgi-protocol-probe.exe"
        self.proc = subprocess.Popen(
            [str(self.wine), str(exe), "-X", "utf8", str(self.lab / "loader_resident.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=wine_env,
        )
        # First line is relay grant; loader never echoes it back.
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(relay_config) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        row = json.loads(line) if line.startswith("{") else {}
        if not row.get("relay_registered"):
            raise RuntimeError("relay_not_registered")
        return {"relay_registered": True, "start_rc": row.get("start_rc")}

    def search(self, _relay_config: dict) -> dict:
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                raise RuntimeError("relay_dead")
            self.proc.stdin.write(json.dumps({"cmd": "search"}) + "\n")
            self.proc.stdin.flush()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("relay_closed")
                if not line.startswith("{"):
                    continue
                row = json.loads(line)
                if row.get("stage") == "search_done":
                    return {
                        "rooms": row.get("rooms") or [],
                        "query_status": row.get("query_status"),
                        "relay_registered": True,
                    }
            raise TimeoutError("search_timeout")

    def stop(self):
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None and self.proc.stdin:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=8)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None


def live_host_ok() -> bool:
    """Authorized collector hosts only: COM or AI Mac. Never invent others."""
    import platform
    from pathlib import Path as P

    node = platform.node()
    home = P.home().name
    # COM hostname has no dots (VKQUANT-COM). AI is literally VKQUANT.AI —
    # do not split on '.' or it becomes 'VKQUANT'.
    if home == "vkquant" and node.split(".")[0] == "VKQUANT-COM":
        return True
    if home == "vk" and (node == "VKQUANT.AI" or node.startswith("VKQUANT.AI.")):
        return True
    return False


def load_live_credentials():
    """Load a clean alt for live mode. Never log secrets. Never returns abcde."""
    from pathlib import Path as P

    if not live_host_ok():
        raise RuntimeError("Live mode restricted to authorized collector hosts")
    # Triple gate: env live flag set by caller, plus explicit allow, plus non-abcde.
    if os.environ.get("SGI_TK_RESIDENT_ALLOW_PROD_LOGIN") != "1":
        raise RuntimeError("prod_login_gate_closed")
    wanted = (os.environ.get("SGI_TK_RESIDENT_ACCOUNT") or "").strip()
    if not wanted:
        raise RuntimeError("live_account_unconfigured")
    if wanted.lower() == "abcde" or wanted in ResidentSession.BLOCKED_LIVE_ACCOUNTS:
        raise RuntimeError("blocked_high_risk_alt")
    sys.path.insert(
        0, str(P.home() / "Library/Application Support/SGI-Room-Monitor/opt")
    )
    from sgi_room_monitor.credentials import load_credentials
    from sgi_room_monitor.provision import default_paths, wine_env

    # Prefer explicit credentials path; 风夜 defaults to fengye file on this tree.
    cred_env = (os.environ.get("SGI_TK_RESIDENT_CREDENTIALS") or "").strip()
    if cred_env:
        cred_file = P(cred_env)
    elif wanted == "风夜":
        cred_file = ROOT / "query-credentials.fengye.json"
    else:
        cred_file = ROOT / "query-credentials.json"
    if not cred_file.is_file():
        raise RuntimeError("credentials_file_missing")
    creds = load_credentials(
        {
            "credentials_file": str(cred_file),
            "account_username": wanted,
        },
        prompt=False,
    )
    if creds["username"] != wanted or not creds["password"]:
        raise RuntimeError("configured_alt_unavailable")
    if creds["username"] in ResidentSession.BLOCKED_LIVE_ACCOUNTS:
        raise RuntimeError("blocked_high_risk_alt")
    paths = default_paths()
    return creds, paths, wine_env


def make_http_handler():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/api", "/status"):
                self.send_error(404)
                return
            with STATE_LOCK:
                body = json.dumps(STATE, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def run_dry_run(cycles: int, interval: float) -> int:
    """Structural dry-run: mock transport, no production login."""
    ledger = OpcodeLedger()
    transport = MockTransport()
    session = ResidentSession(
        transport,
        mock_search_fn,
        ledger=ledger,
        account="mock-alt",
        leave_hall_after_grant=True,
        allow_live_login=False,
    )
    update_state(phase="establishing", mode="dry-run", account="mock-alt")
    # Password never leaves this scope; value is fake for mock login_body only.
    session.establish("mock-alt", "dry-run-password-not-real", wait_seconds=2.0)
    update_state(
        phase="ready",
        mode="dry-run",
        account="mock-alt",
        session_id=session.session_id,
        enter_count=ledger.count(CMD_ENTER),
        login_count=ledger.count(CMD_LOGIN),
        logout_count=ledger.count(CMD_LOGOUT),
        hall_presence=session.hall_presence,
        room_list_visible_expected=session.room_list_visible_expected,
        presence_mechanism=session.presence_mechanism,
        opensession_join=False,
    )
    enter_at_start = ledger.count(CMD_ENTER)
    logout_at_start = ledger.count(CMD_LOGOUT)
    login_at_start = ledger.count(CMD_LOGIN)
    for i in range(cycles):
        if STOP:
            break
        result = session.search_once()
        update_state(
            phase="ready",
            ok=True,
            rooms=result["rooms"],
            query_status=result["query_status"],
            observed_at=result["observed_at"],
            search_cycles=result["search_cycles"],
            enter_count=result["enter_count"],
            logout_count=result["logout_count"],
            login_count=result["login_count"],
            session_id=result["session_id"],
            hall_presence=result["hall_presence"],
            room_list_visible_expected=result["room_list_visible_expected"],
            presence_mechanism=result["presence_mechanism"],
            opensession_join=False,
            error=None,
        )
        log_event(
            {
                "ts": time.time(),
                "event": "search",
                "mode": "dry-run",
                "cycle": i + 1,
                "query_status": result["query_status"],
                "room_count": len(result["rooms"]),
                "enter_count": result["enter_count"],
                "logout_count": result["logout_count"],
                "hall_presence": result["hall_presence"],
                "room_list_visible_expected": result["room_list_visible_expected"],
            }
        )
        if ledger.count(CMD_ENTER) != enter_at_start:
            raise RuntimeError("dry-run re-sent enter")
        if ledger.count(CMD_LOGOUT) != logout_at_start:
            raise RuntimeError("dry-run sent logout during search")
        if ledger.count(CMD_LOGIN) != login_at_start:
            raise RuntimeError("dry-run re-sent login")
        if i + 1 < cycles and interval > 0:
            time.sleep(interval)
    session.close(send_logout=True)
    update_state(
        phase="stopped",
        logout_count=ledger.count(CMD_LOGOUT),
        enter_count=ledger.count(CMD_ENTER),
    )
    summary = {
        "ok": True,
        "mode": "dry-run",
        "account": "mock-alt",
        "login_count": ledger.count(CMD_LOGIN),
        "enter_count": ledger.count(CMD_ENTER),
        "logout_count": ledger.count(CMD_LOGOUT),
        "search_cycles": session.search_cycles,
        "query_status": session.last_query_status,
        "rooms": session.last_rooms,
        "observed_at": session.last_observed_at,
        "hall_presence": session.hall_presence,
        "room_list_visible_expected": session.room_list_visible_expected,
        "presence_mechanism": session.presence_mechanism,
        "opensession_join": False,
        "assert_no_reenter": ledger.count(CMD_ENTER) == 1,
        # leave_hall_after_grant: logout happens at establish (leave list), not mid-search.
        "assert_logout_once_after_grant": ledger.count(CMD_LOGOUT) == 1,
        "assert_not_on_room_list": session.hall_presence == PRESENCE_LEFT_AFTER_GRANT
        and not session.room_list_visible_expected,
    }
    print(json.dumps(summary, ensure_ascii=False))
    ok = (
        summary["assert_no_reenter"]
        and summary["assert_logout_once_after_grant"]
        and summary["assert_not_on_room_list"]
    )
    return 0 if ok else 2


def run_live(interval: float, http_enable: bool) -> int:
    """Live resident loop on authorized collector host. Refuses abcde. Not default."""
    from pathlib import Path as P

    if os.environ.get("SGI_TK_RESIDENT_LIVE") != "1":
        raise RuntimeError("SGI_TK_RESIDENT_LIVE not set")
    if os.environ.get("SGI_TK_RESIDENT_ALLOW_PROD_LOGIN") != "1":
        raise RuntimeError("prod_login_gate_closed")
    if not live_host_ok():
        raise RuntimeError("Live mode restricted to authorized collector hosts")

    process_names = subprocess.check_output(["ps", "-axo", "comm="], text=True).splitlines()
    monitor = str(P.home() / "Library/Application Support/SGI-Wine/prefix-monitor") + "/"
    running = [
        x
        for x in process_names
        if x.startswith(monitor) and x.lower().endswith(("/sanguo.exe", "/sanpk.exe"))
    ]
    if running:
        raise RuntimeError("Stop the monitor lobby/game before resident collector")

    creds, paths, wine_env_fn = load_live_credentials()
    username = creds["username"]
    password = creds["password"]
    del creds

    wine = Path(paths["wine"])
    prefix = P.home() / "Library/Application Support/SGI-Wine/prefix-monitor"
    wine_env = wine_env_fn(wine, prefix)
    relay = WineRelaySearch(wine, prefix, ROOT)

    if http_enable:
        server = ThreadingHTTPServer(DEFAULT_HTTP, make_http_handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()

    failures = 0
    session = None
    ledger = OpcodeLedger()
    try:
        while not STOP:
            try:
                update_state(phase="establishing", mode="live", error=None)
                transport = SocketTransport()
                ledger = OpcodeLedger()

                def search_fn(cfg):
                    if relay.proc is None or relay.proc.poll() is not None:
                        relay.start(cfg, wine_env)
                    return relay.search(cfg)

                if username in ResidentSession.BLOCKED_LIVE_ACCOUNTS:
                    raise RuntimeError("blocked_high_risk_alt")
                session = ResidentSession(
                    transport,
                    search_fn,
                    ledger=ledger,
                    account=username,
                    leave_hall_after_grant=True,
                    allow_live_login=True,
                )
                session.establish(username, password)
                # Start relay once with the grant from enter ack.
                relay.start(session.relay_config, wine_env)
                # Replace search_fn to reuse the already-started relay.
                session.search_fn = relay.search
                failures = 0
                update_state(
                    phase="ready",
                    mode="live",
                    account=username,
                    session_id=session.session_id,
                    enter_count=ledger.count(CMD_ENTER),
                    login_count=ledger.count(CMD_LOGIN),
                    logout_count=ledger.count(CMD_LOGOUT),
                    hall_presence=session.hall_presence,
                    room_list_visible_expected=session.room_list_visible_expected,
                    presence_mechanism=session.presence_mechanism,
                    opensession_join=False,
                )
                while not STOP:
                    result = session.search_once()
                    update_state(
                        phase="ready",
                        ok=True,
                        rooms=result["rooms"],
                        query_status=result["query_status"],
                        observed_at=result["observed_at"],
                        search_cycles=result["search_cycles"],
                        enter_count=result["enter_count"],
                        logout_count=result["logout_count"],
                        login_count=result["login_count"],
                        session_id=result["session_id"],
                        hall_presence=result["hall_presence"],
                        room_list_visible_expected=result["room_list_visible_expected"],
                        presence_mechanism=result["presence_mechanism"],
                        opensession_join=False,
                        error=None,
                    )
                    log_event(
                        {
                            "ts": time.time(),
                            "event": "search",
                            "mode": "live",
                            "query_status": result["query_status"],
                            "room_count": len(result["rooms"]),
                            "enter_count": result["enter_count"],
                            "logout_count": result["logout_count"],
                            "session_id": result["session_id"],
                            "hall_presence": result["hall_presence"],
                            "room_list_visible_expected": result[
                                "room_list_visible_expected"
                            ],
                        }
                    )
                    deadline = time.time() + interval
                    while not STOP and time.time() < deadline:
                        # Hall TCP is usually logged out after grant; only drain
                        # while still marked in_room (stay-in-hall mode).
                        if session.hall_presence == "in_room":
                            try:
                                session.transport.recv_frames(time.monotonic() + 0.5)
                            except ConnectionError:
                                raise
                        time.sleep(0.5)
            except Exception as exc:
                failures += 1
                update_state(
                    phase="reconnecting",
                    ok=False,
                    error=type(exc).__name__,
                    enter_count=ledger.count(CMD_ENTER) if ledger else 0,
                    logout_count=ledger.count(CMD_LOGOUT) if ledger else 0,
                )
                log_event(
                    {
                        "ts": time.time(),
                        "event": "session_error",
                        "error_type": type(exc).__name__,
                        "failures": failures,
                    }
                )
                try:
                    relay.stop()
                except Exception:
                    pass
                if session is not None:
                    try:
                        session.close(send_logout=True)
                    except Exception:
                        pass
                    session = None
                delay = reconnect_delay(failures)
                log_event(
                    {
                        "ts": time.time(),
                        "event": "reconnect_backoff",
                        "failures": failures,
                        "delay_seconds": round(delay, 2),
                    }
                )
                end = time.time() + delay
                while not STOP and time.time() < end:
                    time.sleep(0.5)
    finally:
        try:
            relay.stop()
        except Exception:
            pass
        if session is not None:
            try:
                session.close(send_logout=True)
            except Exception:
                pass
        update_state(phase="stopped")
    return 0


def run_live_once(cycles: int, interval: float) -> int:
    """One-shot live: establish + N SearchSession + clean stop. No KeepAlive loop."""
    from pathlib import Path as P

    if os.environ.get("SGI_TK_RESIDENT_LIVE") != "1":
        raise RuntimeError("SGI_TK_RESIDENT_LIVE not set")
    if os.environ.get("SGI_TK_RESIDENT_ALLOW_PROD_LOGIN") != "1":
        raise RuntimeError("prod_login_gate_closed")
    if not live_host_ok():
        raise RuntimeError("Live mode restricted to authorized collector hosts")

    process_names = subprocess.check_output(["ps", "-axo", "comm="], text=True).splitlines()
    monitor = str(P.home() / "Library/Application Support/SGI-Wine/prefix-monitor") + "/"
    running = [
        x
        for x in process_names
        if x.startswith(monitor) and x.lower().endswith(("/sanguo.exe", "/sanpk.exe"))
    ]
    if running:
        raise RuntimeError("Stop the monitor lobby/game before resident collector")

    probe = ROOT / "python32" / "sgi-protocol-probe.exe"
    if not probe.is_file():
        raise RuntimeError("wine_python32_missing")

    creds, paths, wine_env_fn = load_live_credentials()
    username = creds["username"]
    password = creds["password"]
    del creds

    wine = Path(paths["wine"])
    if not wine.exists():
        raise RuntimeError("wine_binary_missing")
    prefix = P.home() / "Library/Application Support/SGI-Wine/prefix-monitor"
    if not prefix.is_dir():
        raise RuntimeError("wine_prefix_monitor_missing")
    wine_env = wine_env_fn(wine, prefix)
    relay = WineRelaySearch(wine, prefix, ROOT)
    ledger = OpcodeLedger()
    session = None
    summary = {
        "ok": False,
        "mode": "live-once",
        "account": username,
        "login_ok": False,
        "enter_once": False,
        "logout_after_grant": False,
        "search_cycles": 0,
        "room_count": 0,
        "query_status": None,
        "hall_presence": None,
        "room_list_visible_expected": None,
        "presence_mechanism": MECHANISM_LEAVE,
        "opensession_join": False,
        "error": None,
        "error_category": None,
    }
    try:
        update_state(phase="establishing", mode="live-once", account=username, error=None)
        transport = SocketTransport()

        def search_fn(cfg):
            if relay.proc is None or relay.proc.poll() is not None:
                relay.start(cfg, wine_env)
            return relay.search(cfg)

        if username in ResidentSession.BLOCKED_LIVE_ACCOUNTS:
            raise RuntimeError("blocked_high_risk_alt")
        session = ResidentSession(
            transport,
            search_fn,
            ledger=ledger,
            account=username,
            leave_hall_after_grant=True,
            allow_live_login=True,
        )
        session.establish(username, password)
        password = None
        summary["login_ok"] = True
        summary["enter_once"] = ledger.count(CMD_ENTER) == 1
        summary["logout_after_grant"] = (
            ledger.count(CMD_LOGOUT) == 1
            and session.hall_presence == PRESENCE_LEFT_AFTER_GRANT
        )
        relay.start(session.relay_config, wine_env)
        session.search_fn = relay.search
        update_state(
            phase="ready",
            mode="live-once",
            account=username,
            session_id=session.session_id,
            enter_count=ledger.count(CMD_ENTER),
            login_count=ledger.count(CMD_LOGIN),
            logout_count=ledger.count(CMD_LOGOUT),
            hall_presence=session.hall_presence,
            room_list_visible_expected=session.room_list_visible_expected,
            presence_mechanism=session.presence_mechanism,
            opensession_join=False,
        )
        for i in range(max(1, cycles)):
            if STOP:
                break
            result = session.search_once()
            update_state(
                phase="ready",
                ok=True,
                rooms=result["rooms"],
                query_status=result["query_status"],
                observed_at=result["observed_at"],
                search_cycles=result["search_cycles"],
                enter_count=result["enter_count"],
                logout_count=result["logout_count"],
                login_count=result["login_count"],
                session_id=result["session_id"],
                hall_presence=result["hall_presence"],
                room_list_visible_expected=result["room_list_visible_expected"],
                presence_mechanism=result["presence_mechanism"],
                opensession_join=False,
                error=None,
            )
            log_event(
                {
                    "ts": time.time(),
                    "event": "search",
                    "mode": "live-once",
                    "cycle": i + 1,
                    "query_status": result["query_status"],
                    "room_count": len(result["rooms"]),
                    "enter_count": result["enter_count"],
                    "logout_count": result["logout_count"],
                    "hall_presence": result["hall_presence"],
                    "room_list_visible_expected": result["room_list_visible_expected"],
                }
            )
            if i + 1 < cycles and interval > 0:
                time.sleep(interval)
        summary.update(
            {
                "ok": True,
                "search_cycles": session.search_cycles,
                "room_count": len(session.last_rooms or []),
                "query_status": session.last_query_status,
                "rooms": session.last_rooms,
                "hall_presence": session.hall_presence,
                "room_list_visible_expected": session.room_list_visible_expected,
                "presence_mechanism": session.presence_mechanism,
                "login_count": ledger.count(CMD_LOGIN),
                "enter_count": ledger.count(CMD_ENTER),
                "logout_count": ledger.count(CMD_LOGOUT),
                "session_id": session.session_id,
                "assert_no_reenter": ledger.count(CMD_ENTER) == 1,
                "assert_logout_once_after_grant": ledger.count(CMD_LOGOUT) == 1,
            }
        )
    except Exception as exc:
        msg = str(exc)
        summary["error"] = type(exc).__name__
        low = msg.lower()
        if summary["error"] == "blocked_high_risk_alt":
            summary["error_category"] = "blocked_account"
        elif "login_failed" in low:
            summary["error_category"] = "password_or_auth"
        elif "wine" in low or "python32" in low or "prefix_monitor" in low:
            summary["error_category"] = "wine_missing_or_broken"
        elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            summary["error_category"] = "network"
        elif "already" in low or "已登录" in msg or "已经登录" in msg:
            summary["error_category"] = "already_logged_in"
        else:
            summary["error_category"] = "other"
        update_state(phase="error", ok=False, error=type(exc).__name__)
        log_event(
            {
                "ts": time.time(),
                "event": "once_error",
                "error_type": type(exc).__name__,
                "error_category": summary["error_category"],
            }
        )
    finally:
        try:
            relay.stop()
        except Exception:
            pass
        if session is not None:
            try:
                session.close(send_logout=True)
            except Exception:
                pass
        password = None
        update_state(phase="stopped")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("ok") else 2



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mock session only; no production login",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=3,
        help="Dry-run search cycles after one login",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Seconds between search-only cycles",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Live mode (COM or AI). Needs SGI_TK_RESIDENT_LIVE=1, SGI_TK_RESIDENT_ALLOW_PROD_LOGIN=1, SGI_TK_RESIDENT_ACCOUNT=<clean-alt>. Refuses abcde.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --live: one establish + --cycles searches then stop (no KeepAlive loop).",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Also serve status on 127.0.0.1:18774 (ignored for --once).",
    )
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    if args.dry_run and args.live:
        print(json.dumps({"ok": False, "error": "choose_dry_run_or_live"}))
        return 2
    if args.once and not args.live:
        print(json.dumps({"ok": False, "error": "once_requires_live"}))
        return 2

    if not args.dry_run and not args.live:
        # Safe default: dry-run so accidental starts never hit production.
        args.dry_run = True

    lock = acquire_lock()
    if lock is None:
        print(json.dumps({"ok": False, "status": "already_running"}, ensure_ascii=False))
        return 0
    try:
        if args.dry_run:
            return run_dry_run(args.cycles, min(args.interval, 0.05) if args.cycles <= 5 else args.interval)
        if args.once:
            return run_live_once(max(1, args.cycles), args.interval)
        return run_live(args.interval, http_enable=args.http)
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
