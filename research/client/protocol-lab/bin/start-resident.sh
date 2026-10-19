#!/usr/bin/env bash
# Start resident collector. Default is dry-run (no production login).
# Live (COM only, clean alt — NEVER abcde):
#   SGI_TK_RESIDENT_LIVE=1 \
#   SGI_TK_RESIDENT_ALLOW_PROD_LOGIN=1 \
#   SGI_TK_RESIDENT_ACCOUNT=<clean-alt> \
#   ./start-resident.sh
# Do not enable casually. abcde is blocked in code as high-risk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${SGI_TK_RESIDENT_PID:-$ROOT/resident.pid}"
LOG_FILE="${SGI_TK_RESIDENT_LOG:-$ROOT/resident.log}"
cd "$ROOT"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo '{"ok":false,"status":"already_running"}'
  exit 0
fi

if [[ "${SGI_TK_RESIDENT_LIVE:-}" == "1" ]]; then
  if [[ "${SGI_TK_RESIDENT_ALLOW_PROD_LOGIN:-}" != "1" ]]; then
    echo '{"ok":false,"error":"prod_login_gate_closed"}' >&2
    exit 2
  fi
  if [[ -z "${SGI_TK_RESIDENT_ACCOUNT:-}" || "${SGI_TK_RESIDENT_ACCOUNT}" == "abcde" ]]; then
    echo '{"ok":false,"error":"blocked_or_unconfigured_alt"}' >&2
    exit 2
  fi
  nohup /usr/bin/python3 bin/sgi_tk_resident.py --live --http >>"$LOG_FILE" 2>&1 &
else
  # Safe default: structural dry-run only.
  nohup /usr/bin/python3 bin/sgi_tk_resident.py --dry-run --cycles 999999 --interval 30 --http >>"$LOG_FILE" 2>&1 &
fi
echo $! >"$PID_FILE"
MODE="dry-run"
if [[ "${SGI_TK_RESIDENT_LIVE:-}" == "1" ]]; then MODE="live"; fi
printf '{"ok":true,"pid":%s,"mode":"%s"}\n' "$(cat "$PID_FILE")" "$MODE"
