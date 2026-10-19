"""Local-first client for SGI-TK feed: prefer resident HTTP/status on this Mac.

Default source is local resident (leave_hall_after_grant path). SSH/COM is only
used when SGI_MONITOR_SOURCE=ssh. Never prints passwords or ingest tokens.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

VERSION = "0.2.0-local"
DEFAULT_HOST = "vkquant@fd7a:115c:a1e0::f930:8943"
REMOTE = "/Users/vkquant/sgi-protocol-lab-20260915/bot_api_cli.py"
DEFAULT_RESIDENT_HTTP = os.environ.get(
    "SGI_RESIDENT_HTTP", "http://127.0.0.1:18774/api"
)
DEFAULT_RESIDENT_STATUS = os.environ.get(
    "SGI_RESIDENT_STATUS",
    str(
        Path.home()
        / "Documents/Coding/三国志internet/research/client/protocol-lab/resident-status.json"
    ),
)


def _read_resident_http(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _read_resident_file(path: str):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _map_resident(state: dict, started: float):
    observed = state.get("observed_at") or state.get("updated_at")
    age = max(0.0, time.time() - float(observed)) if observed is not None else None
    phase = state.get("phase") or ""
    query_status = state.get("query_status") or "query_failed"
    rooms = state.get("rooms") if isinstance(state.get("rooms"), list) else []
    account = state.get("account") or "unconfigured"
    if account == "abcde":
        return {
            "ok": False,
            "status": "blocked_high_risk_alt",
            "rooms": [],
            "message": "abcde 已弃用，禁止用于监控上传",
            "updated_at": observed,
            "age_seconds": round(age, 1) if age is not None else None,
            "source": "VKQUANT.AI-resident",
            "game_start_confirmed": False,
        }
    if phase in ("error", "stopped") and not state.get("ok"):
        return {
            "ok": False,
            "status": "query_failed",
            "message": state.get("error") or "常驻采集未就绪",
            "rooms": [],
            "updated_at": observed,
            "age_seconds": round(age, 1) if age is not None else None,
            "source": "VKQUANT.AI-resident",
            "game_start_confirmed": False,
        }
    if observed is None or age is None:
        return None
    # Accept ready/establishing/reconnecting snapshots that are recent.
    if age <= 90 and phase in ("ready", "establishing", "reconnecting", "stopped"):
        # stopped-but-ok once snapshot is only useful briefly; live should be ready.
        if phase == "stopped" and age > 45:
            return None
        return {
            "ok": True if state.get("ok", True) else False,
            "status": query_status,
            "account": account,
            "platform_room": "三国对战房 / 多线2（主线）",
            "platform_room_id": 1001,
            "rooms": rooms,
            "updated_at": float(observed),
            "age_seconds": round(age, 1),
            "refreshing": phase in ("establishing", "reconnecting"),
            "source": "VKQUANT.AI-resident",
            "capture_method": "resident_leave_hall_after_grant",
            "game_start_confirmed": bool(state.get("game_start_confirmed")),
            "hall_presence": state.get("hall_presence"),
            "enter_count": state.get("enter_count"),
            "logout_count": state.get("logout_count"),
            "login_count": state.get("login_count"),
            "presence_mechanism": state.get("presence_mechanism"),
            "fresh_since_request": float(observed) >= started,
        }
    return None


def fetch_local(fresh: bool = False, timeout: float = 60.0):
    started = time.time()
    deadline = time.monotonic() + timeout
    http = DEFAULT_RESIDENT_HTTP
    status_path = DEFAULT_RESIDENT_STATUS
    last = None
    while time.monotonic() < deadline:
        state = _read_resident_http(http) or _read_resident_file(status_path)
        if not state:
            last = {
                "ok": False,
                "status": "collector_unavailable",
                "rooms": [],
                "message": "无法连接本机常驻采集（HTTP/status）",
            }
            time.sleep(1)
            continue
        mapped = _map_resident(state, started)
        last = mapped
        if mapped and mapped.get("ok"):
            if not fresh or mapped.get("fresh_since_request"):
                mapped = dict(mapped)
                mapped.pop("fresh_since_request", None)
                return mapped
        time.sleep(1)
    if last and isinstance(last, dict):
        last = dict(last)
        last.pop("fresh_since_request", None)
        if last.get("ok"):
            return last
        return last
    return {
        "ok": False,
        "status": "timeout",
        "rooms": [],
        "message": "等待本机常驻最新结果超时",
    }


def fetch_ssh(host: str, fresh: bool = False):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:@%\-]*", host):
        raise ValueError("Invalid SSH host or alias")
    if not shutil.which("ssh"):
        return {
            "ok": False,
            "status": "ssh_unavailable",
            "rooms": [],
            "message": "需要安装 OpenSSH 客户端",
        }
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        host,
        "python3 " + REMOTE + (" --fresh" if fresh else ""),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=75
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "ssh_timeout",
            "rooms": [],
            "message": "连接采集 Mac 超时",
        }
    try:
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError()
        if proc.returncode != 0 and result["ok"]:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        return {
            "ok": False,
            "status": "ssh_or_remote_error",
            "rooms": [],
            "message": "请检查 SSH 授权、主机连接和远端列表服务；未获得有效数据",
        }


def fetch(host=None, fresh: bool = False):
    source = (os.environ.get("SGI_MONITOR_SOURCE") or "local").strip().lower()
    if source in ("local", "resident"):
        return fetch_local(fresh=fresh)
    if source == "ssh":
        return fetch_ssh(host or os.environ.get("SGI_MONITOR_SSH_HOST", DEFAULT_HOST), fresh=fresh)
    # auto: local first, no COM fallback (avoid abcde/COM dependency)
    return fetch_local(fresh=fresh)


def brief(result):
    if not result["ok"]:
        return result.get("message", "查询失败")
    when = datetime.fromtimestamp(result["updated_at"]).astimezone().isoformat(
        timespec="seconds"
    )
    lines = [f"多线2 · {when} · 数据距今 {result['age_seconds']} 秒"]
    if result["status"] == "unconfirmed_empty":
        lines.append("本轮未收到房间回应，不能据此确认无房或已经开局。")
    else:
        lines.extend(
            f"{x['name']} | 房主 {x['host']} | {x['current']}/{x['maximum']} | ID {x['id']}"
            for x in result["rooms"]
        )
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["query", "brief"])
    p.add_argument(
        "--host", default=os.environ.get("SGI_MONITOR_SSH_HOST", DEFAULT_HOST)
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="Wait for a new completed query, up to 60 seconds",
    )
    p.add_argument("--version", action="version", version=VERSION)
    args = p.parse_args()
    try:
        result = fetch(args.host, args.fresh)
    except ValueError:
        result = {
            "ok": False,
            "status": "invalid_host",
            "rooms": [],
            "message": "SSH 主机参数无效",
        }
    print(brief(result) if args.command == "brief" else json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
