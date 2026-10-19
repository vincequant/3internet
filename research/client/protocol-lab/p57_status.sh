#!/bin/bash
# One-shot read-only status for the P57 entry run: shadow scene mode + host L table
# + recorder freshness. Never writes to either client.
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-protocol-lab-20260915/shadow"
HOSTPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10"
echo "== shadow scene (mode 3 = inside the map) =="
"$WINE" "$P32" -X utf8 "$S/tools/shadow_mode.py" --bridge "$Z\\bridge" 2>&1 | tail -2
echo "== host application rows (the ONLY hide criterion) =="
HP=$(WINEPREFIX="$HOSTPREFIX" "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tail -1)
case "$HP" in
  ''|ERR*) echo "  host SANPK not running (pid='$HP')" ;;
  *)
    WINEPREFIX="$HOSTPREFIX" SGI_BRIDGE_Z="$Z\\bridge" "$WINE" "$P32" -X utf8 \
      "$S/tools/p32_app_rows_read.py" "$HP" 2>/dev/null | tail -1 | python3 -c "
import json,sys
try: d=json.loads(sys.stdin.readline())
except Exception: print('  (unreadable)'); raise SystemExit
seen=0
for t in d.get('tables',[]):
    rows=[(r.get('i'), r.get('name'), r.get('id'), r.get('state')) for r in t.get('rows',[]) if r.get('id')]
    if not rows: continue
    seen+=1
    print('  [%s] %s' % (t.get('table_hypothesis'), rows))
if not seen: print('  (no populated row table found)')
names=[r.get('name') for t in d.get('tables',[]) for r in t.get('rows',[]) if r.get('id')]
print('  ghost row present:', '待秋至' in names)
"
    ;;
esac
echo "== recorder freshness (newest session) =="
SESS=$(ls -dt "$HOME/sgi-protocol-lab-20260915/fengye-hub-session"/run-*-shadow 2>/dev/null | head -1)
if [ -n "$SESS" ]; then
  echo "  session: $(basename "$SESS")"
  python3 - "$SESS" <<'PY'
import json, os, sys, time
sess = sys.argv[1]
p = os.path.join(sess, 'packets.jsonl')
now = time.time()
last = None; n = 0; recent = 0
try:
    for line in open(p):
        try: e = json.loads(line)
        except Exception: continue
        if e.get('ev') != 'received_packet':
            continue
        w = e.get('wall') or 0
        n += 1
        if w > (last or 0):
            last = w
            o = e.get('object') or {}
            lastdesc = '%s cmd=%s len=%s' % (o.get('class_name'), o.get('cmd'), e.get('length'))
        if now - w < 120:
            recent += 1
except FileNotFoundError:
    print('  no packets.jsonl'); raise SystemExit
print('  packets total=%d in-last-120s=%d' % (n, recent))
if last:
    print('  last rx %ds ago: %s' % (int(now - last), lastdesc))
PY
  [ -f "$SESS/state.json" ] && python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print('  recorder: connected=%s ready=%s sync_state=%s tx_seq=%s rx=%s' % (
  d.get('connected'), d.get('application_ready'), d.get('native_sync_state'),
  d.get('native_tx_seq'), d.get('received')))
" "$SESS/state.json"
else
  echo "  no session dir"
fi
echo "== crash ledger mtime (new lines = crashes) =="
CR="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/sgi-crash-context.bin"
[ -f "$CR" ] && stat -f "  %z bytes, mtime %Sm" -t "%H:%M:%S" "$CR" || echo "  (no crash file)"
