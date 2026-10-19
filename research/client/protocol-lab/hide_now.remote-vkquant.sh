#!/bin/bash
# Fire the in-client D8 agent now, then verify on the host APPLICATION rows (L table).
# The DLL member list keeps the ghost on purpose, so it must not be used here.
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-protocol-lab-20260915/shadow"
NICK="${JOIN_NICKNAME:-待秋至}"
wpid() {
  WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10" \
    "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tail -1
}
row_present() {
  local hp; hp=$(wpid); case "$hp" in ''|ERR*) return 2 ;; esac
  WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10" \
    SGI_BRIDGE_Z="$Z\\bridge" "$WINE" "$P32" -X utf8 "$S/tools/p32_app_rows_read.py" "$hp" 2>/dev/null \
    | tail -1 | python3 -c "
import json,sys
try: d=json.loads(sys.stdin.readline())
except Exception: sys.exit(2)
# 2026-10-19: the table label flips between L_pair_lower / unpaired_unknown depending
# on pairing state. Scanning only 'L_pair_lower' made a dead client look 'hidden'
# (live false positive at 08:12). Judge on the NAME across every populated table.
names=[r.get('name') for t in d.get('tables',[]) for r in t.get('rows',[]) if r.get('id')]
sys.exit(0 if '${NICK}' in names else 1)
"
}
echo "== hide now =="
for attempt in 1 2 3; do
  rm -f shadow_go.flag shadow_d8_receipt.bin
  bash inject.sh --force 2>&1 | tail -1
  bash fire.sh >/dev/null
  sleep 5
  [ -s shadow_d8_receipt.bin ] && xxd -l 8 shadow_d8_receipt.bin || echo "  attempt $attempt: no receipt"
  if row_present; then echo "  attempt $attempt: host L-table still lists ${NICK}"
  else
    echo "  attempt $attempt: row GONE from host L-table -> hidden"
    python3 - <<'PY2'
import json, time
open('shadow_hidden.json', 'w').write(json.dumps({
    'verified': True, 'at': time.time(), 'by': 'host_L_table',
    'note': 'application row gone on the host; DLL member row intentionally kept'}, ensure_ascii=False))
print('hidden marker written')
PY2
    exit 0
  fi
done
echo "!! still listed after 3 attempts"; exit 1
