#!/bin/bash
# P57 entry watcher: samples the shadow scene + host L table + recorder every 3 s.
# Read-only. Logs one compact line per tick so the entry transition can be replayed.
# Usage: bash p57_watch_entry.sh [ticks] [out]
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-protocol-lab-20260915/shadow"
HOSTPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10"
TICKS="${1:-200}"
OUT="${2:-logs/p57-entry-watch.log}"
: > "$OUT"

scene_mode() {
  "$WINE" "$P32" -X utf8 "$S/tools/shadow_mode.py" --bridge "$Z\\bridge" 2>/dev/null | tail -1 \
    | python3 -c "
import json,sys
try: d=json.loads(sys.stdin.readline())
except Exception: print('mode=?'); raise SystemExit
print('mode=%s phase=%s in_map=%s' % (d.get('mode','?'), d.get('phase','?'), d.get('in_map')))
" 2>/dev/null
}

host_rows() {
  local hp
  hp=$(WINEPREFIX="$HOSTPREFIX" "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tail -1)
  if [ -z "$hp" ] || [ "$hp" = "ERR" ]; then echo "host=none"; return; fi
  WINEPREFIX="$HOSTPREFIX" SGI_BRIDGE_Z="$Z\\bridge" "$WINE" "$P32" -X utf8 \
    "$S/tools/p32_app_rows_read.py" "$hp" 2>/dev/null | tail -1 | python3 -c "
import json,sys
try: d=json.loads(sys.stdin.readline())
except Exception: print('host=?'); raise SystemExit
names=[r.get('name') for t in d.get('tables',[]) for r in t.get('rows',[]) if r.get('id')]
print('hostrows=%s ghost=%s' % (','.join(str(n) for n in names) or '-', '待秋至' in names))
"
}

rec_state() {
  python3 - "$HOME/sgi-protocol-lab-20260915/fengye-hub-session/active.json" <<'PY'
import json, os, sys
try:
    p = json.load(open(sys.argv[1]))
    d = p['directory']
except Exception:
    print('rec=none'); raise SystemExit
try:
    s = json.load(open(os.path.join(d, 'state.json')))
except Exception:
    print('rec=nostate'); raise SystemExit
last = '-'
try:
    lines = open(os.path.join(d, 'packets.jsonl'), encoding='utf-8').read().strip().splitlines()
    if lines:
        e = json.loads(lines[-1])
        o = e.get('object') or {}
        last = '%s/%s' % (o.get('class_name') or '?', o.get('cmd'))
except Exception:
    pass
print('sync=%s tx=%s rx=%s last=%s' % (s.get('native_sync_state'), s.get('native_tx_seq'),
      s.get('received'), last))
PY
}

for i in $(seq 1 "$TICKS"); do
  echo "$(date +%H:%M:%S) $(scene_mode) | $(host_rows) | $(rec_state)" >> "$OUT"
  sleep 3
done
echo "watch done: $TICKS ticks -> $OUT"
