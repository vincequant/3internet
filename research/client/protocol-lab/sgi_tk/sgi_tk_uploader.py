"""Query the dedicated collector and upload one sanitized snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENT_CANDIDATES = [
    Path(os.environ.get("SGI_BOT_CLIENT", "")),
    ROOT.parents[3] / "deliverables" / "sgi-grok-bot-0.1.0" / "sgi_bot_client.py",
    Path("/Users/vk/Documents/Coding/三国志internet/deliverables/sgi-grok-bot-0.1.0/sgi_bot_client.py"),
    Path.home() / "Library/Application Support/SGI-TK-Feed/sgi_bot_client.py",
]

SCHEMA_VERSION = 1
SOURCE_ID = "sgi-tk-monitor"
DEFAULT_UPLOAD_URL = "https://www.vkquant.ai/api/sgi-tk/ingest"
MAX_ROOMS = 32


def load_client():
    for path in CLIENT_CANDIDATES:
        if path and path.is_file():
            sys.path.insert(0, str(path.parent))
            import sgi_bot_client
            return sgi_bot_client, path
    raise FileNotFoundError("sgi_bot_client.py not found")


def sanitize_text(value, max_len=128):
    return "".join(ch for ch in str(value or "") if ord(ch) >= 32).strip()[:max_len]


def normalize_rooms(rooms):
    out = []
    for row in rooms or []:
        if not isinstance(row, dict):
            continue
        try:
            current = int(row["current"])
            maximum = int(row["maximum"])
        except (KeyError, TypeError, ValueError):
            continue
        room_id = sanitize_text(row.get("id"), 64)
        name = sanitize_text(row.get("name"))
        if not room_id or not name or current < 0 or maximum < 1 or current > maximum:
            continue
        out.append({
            "id": room_id,
            "name": name,
            "host": sanitize_text(row.get("host")),
            "current": current,
            "maximum": maximum,
        })
        if len(out) >= MAX_ROOMS:
            break
    return out


def build_payload(result, now=None):
    now = time.time() if now is None else now
    ok = bool(result.get("ok"))
    status = sanitize_text(result.get("status") or ("replies_received" if ok else "query_failed"), 64)
    observed = result.get("updated_at")
    try:
        observed_at = float(observed)
    except (TypeError, ValueError):
        observed_at = now
    rooms = normalize_rooms(result.get("rooms"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "observed_at": observed_at,
        "ok": ok,
        "query_status": status,
        "rooms": rooms if ok else rooms,
        "game_start_confirmed": False,
        "message": sanitize_text(result.get("message"), 240),
        "sequence": int(observed_at * 1000),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    payload["idempotency_key"] = f"{SOURCE_ID}:{payload['sequence']}:{status}:{digest}"
    return payload


def load_secret(path=None):
    env_path = Path(path or os.environ.get("SGI_TK_INGEST_ENV", Path.home() / ".config/sgi-tk/ingest.env"))
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("SGI_TK_INGEST_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'").strip('"')
    return os.environ.get("SGI_TK_INGEST_TOKEN", "").strip()



def upload(payload, url, token, timeout=20):
    """POST ingest payload. Force IPv4 to avoid broken local AAAA/TLS MITM."""
    import socket

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "sgi-tk-uploader/0.1",
            "X-SGI-TK-Ingest-Token": token,
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    _orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"error": "http_error"}
        return exc.code, parsed
    finally:
        socket.getaddrinfo = _orig_getaddrinfo


def run_once(fresh=False, host=None):
    client, _client_path = load_client()
    ssh_host = host or os.environ.get("SGI_MONITOR_SSH_HOST", client.DEFAULT_HOST)
    result = client.fetch(ssh_host, fresh=fresh)
    payload = build_payload(result)
    token = load_secret()
    url = os.environ.get("SGI_TK_UPLOAD_URL", DEFAULT_UPLOAD_URL)
    if not token:
        return {
            "ok": False,
            "status": "auth_failed",
            "message": "upload token missing",
            "query": {k: result.get(k) for k in ("ok", "status", "updated_at") if k in result},
        }
    status, body = upload(payload, url, token)
    return {
        "ok": 200 <= status < 300 and body.get("ok") is not False,
        "http_status": status,
        "upload": {k: body.get(k) for k in ("ok", "action", "error") if k in body},
        "query": {
            "ok": result.get("ok"),
            "status": result.get("status"),
            "observed_at": payload["observed_at"],
            "room_count": len(payload["rooms"]),
        },
    }


def main():
    fresh = "--fresh" in sys.argv
    report = run_once(fresh=fresh)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
