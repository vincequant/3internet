#!/bin/bash
# Paired round-progress watch: ghost vs host, every cycle. Read-only.
# Usage: pairwatch.sh [sleep_seconds] [duration_seconds]
# Output: logs/pairwatch-<ts>.jsonl  (one JSON line per cycle)
cd "$(dirname "$0")/.."
INTERVAL=${1:-5}
DURATION=${2:-900}
OUT="$HOME/sgi-protocol-lab-20260915/shadow/logs/pairwatch-$(date +%Y%m%d-%H%M%S).jsonl"
echo "PAIRWATCH OUT=$OUT"
END=$(( $(date +%s) + DURATION ))
probe() { # $1 = prefix path
  ( export WINEPREFIX="$1"; export WINEDEBUG=-all
    export DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib"
    unset DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH DYLD_INSERT_LIBRARIES
    "$HOME/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine" \
      "$HOME/sgi-protocol-lab-20260915/python32/python.exe" \
      "$HOME/sgi-protocol-lab-20260915/shadow/tools/roundprobe.py" \
      --bridge 'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\bridge' --samples 1 --interval 1 2>/dev/null \
    | grep '^{' | tail -1 )
}
while [ $(date +%s) -lt $END ]; do
  TS=$(date +%H:%M:%S)
  G=$(probe "$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow")
  H=$(probe "$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10")
  python3 - "$TS" "$G" "$H" <<'PY' >> "$OUT"
import json,sys
ts=sys.argv[1]
def pick(s):
    try: d=json.loads(s)
    except Exception: return None
    if not d: return None
    return {k:d.get(k) for k in ("tick_state_G68","phase_4d8","f_4d0","f_4d6","f_6bc","sync_84a8","queue_84b4","ctr_8444","my_slot_6c0")}
g=pick(sys.argv[2]); h=pick(sys.argv[3])
print(json.dumps({"ts":ts,"ghost":g,"host":h}, ensure_ascii=False))
PY
  sleep "$INTERVAL"
done
echo "PAIRWATCH DONE $OUT"
