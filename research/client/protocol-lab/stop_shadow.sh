#!/bin/bash
# Stop the shadow client session (prefix-scoped; never touches other prefixes).
# 1) STOP marker lets the held launcher close its hall session gracefully.
# 2) SIGTERM the StartServer helper (recorded pid; guarded against stale/reused pid).
# 3) wineserver -k for prefix-fengye-shadow as a backstop.
set -u
SHADOW="$HOME/sgi-protocol-lab-20260915/shadow"
export WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow"
export DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib"
unset DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH DYLD_INSERT_LIBRARIES
touch "$SHADOW/STOP"
pkill -f "shadow_round_keeper" 2>/dev/null || true
PIDFILE="$SHADOW/helper.pid"
if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    # Guard: only kill if the live process really belongs to the shadow lab
    # (stale pid files must never SIGTERM an unrelated reused pid).
    ENVLINE=$(ps eww -p "$PID" 2>/dev/null)
    case "$ENVLINE" in
      *prefix-fengye-shadow*|*sgi-protocol-lab-20260915/shadow*)
        kill "$PID" 2>/dev/null && echo "helper $PID SIGTERM sent" || echo "helper kill failed"
        sleep 3 ;;
      *)
        echo "helper pid $PID looks unrelated (reused); skip kill" ;;
    esac
  else
    echo "helper pid not alive"
  fi
fi
WINESERVER="$HOME/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wineserver"
if [ -x "$WINESERVER" ]; then
  "$WINESERVER" -k 2>/dev/null && echo "wineserver -k issued" || echo "wineserver -k rc=$?"
fi
sleep 2
rm -f "$SHADOW/STOP"
LEFT=$(ps aux | grep -F "prefix-fengye-shadow" | grep -v grep | wc -l | tr -d ' ')
echo "shadow-prefix processes remaining (heuristic): $LEFT"
echo "stop complete"
