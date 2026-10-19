"""Single-instance 30s uploader. Skip overlapping cycles instead of queueing."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import sys
import time
from pathlib import Path

from sgi_tk_uploader import run_once

INTERVAL = int(os.environ.get("SGI_TK_INTERVAL_SECONDS", "30"))
LOCK_PATH = Path(os.environ.get(
    "SGI_TK_LOCK",
    Path.home() / "Library/Application Support/SGI-TK-Feed/scheduler.lock",
))
STATE_PATH = Path(os.environ.get(
    "SGI_TK_STATE",
    Path.home() / "Library/Logs/sgi-tk-feed-state.json",
))
LOG_PATH = Path(os.environ.get(
    "SGI_TK_LOG",
    Path.home() / "Library/Logs/sgi-tk-feed.jsonl",
))
MAX_LOG_BYTES = 256 * 1024
STOP = False


def log_event(event):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES:
        rotated = LOG_PATH.with_suffix(".jsonl.1")
        rotated.unlink(missing_ok=True)
        LOG_PATH.replace(rotated)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def acquire_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+")
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


def backoff_seconds(failures):
    return min(60, 5 * (2 ** max(0, failures - 1)))


def loop():
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    lock = acquire_lock()
    if lock is None:
        print(json.dumps({"ok": False, "status": "already_running"}, ensure_ascii=False))
        return 0
    failures = 0
    paused = False
    write_state({"pid": os.getpid(), "status": "running", "started_at": time.time()})
    try:
        while not STOP:
            cycle_started = time.time()
            if paused:
                log_event({"ts": cycle_started, "event": "paused_auth"})
                write_state({
                    "pid": os.getpid(),
                    "status": "paused_auth",
                    "updated_at": cycle_started,
                    "needs_attention": True,
                })
                time.sleep(min(60, INTERVAL))
                continue
            try:
                report = run_once(fresh=False)
            except Exception as exc:
                report = {"ok": False, "status": "scheduler_error", "message": type(exc).__name__}
            http_status = report.get("http_status")
            query_ok = (report.get("query") or {}).get("ok")
            upload_ok = report.get("ok")
            auth_error = (report.get("upload") or {}).get("error")
            auth_failed = (
                (http_status in (401, 403) and auth_error in ("unauthorized", "forbidden"))
                or report.get("status") == "auth_failed"
            )
            event = {
                "ts": time.time(),
                "event": "cycle",
                "query_ok": query_ok,
                "query_status": (report.get("query") or {}).get("status"),
                "observed_at": (report.get("query") or {}).get("observed_at"),
                "http_status": http_status,
                "upload_ok": upload_ok,
                "action": (report.get("upload") or {}).get("action"),
            }
            log_event(event)
            write_state({
                "pid": os.getpid(),
                "status": "paused_auth" if auth_failed else "running",
                "updated_at": event["ts"],
                "last_cycle": event,
                "needs_attention": auth_failed,
            })
            if auth_failed:
                paused = True
                continue
            if upload_ok:
                failures = 0
                sleep_for = INTERVAL
            else:
                failures += 1
                sleep_for = backoff_seconds(failures)
            elapsed = time.time() - cycle_started
            if elapsed >= INTERVAL:
                continue
            deadline = time.time() + max(1, sleep_for - elapsed)
            while not STOP and time.time() < deadline:
                time.sleep(1)
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        print(json.dumps(run_once(fresh="--fresh" in sys.argv), ensure_ascii=False))
        raise SystemExit(0)
    raise SystemExit(loop())
