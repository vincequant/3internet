#!/usr/bin/env bash
# Stop resident collector. Does not touch Wine prefix-main / main account.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${SGI_TK_RESIDENT_PID:-$ROOT/resident.pid}"
STATUS_FILE="${SGI_TK_RESIDENT_STATUS:-$ROOT/resident-status.json}"

stopped=false
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if ! kill -0 "$pid" 2>/dev/null; then
        stopped=true
        break
      fi
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
      stopped=true
    fi
  else
    stopped=true
  fi
  rm -f "$PID_FILE"
fi

# Best-effort: any leftover resident by lock/cmdline (alt only).
pkill -f "bin/sgi_tk_resident.py" 2>/dev/null || true

echo "{\"ok\":true,\"status\":\"stopped\",\"had_pid\":$stopped}"
