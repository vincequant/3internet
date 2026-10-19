#!/bin/bash
# Stop the shadow client session (prefix-scoped; never touches other prefixes).
# 1) STOP marker lets the held launcher close its hall session gracefully.
# 2) SIGTERM the StartServer helper (recorded pid) so it can run its finally.
# 3) wineserver -k for prefix-fengye-shadow as a backstop.
set -u
SHADOW="$HOME/sgi-protocol-lab-20260915/shadow"
export WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow"
export DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib"
unset DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH DYLD_INSERT_LIBRARIES
touch "$SHADOW/STOP"
PIDFILE="$SHADOW/helper.pid"
if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null && echo "helper $PID SIGTERM sent" || echo "helper kill failed"
    sleep 3
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
