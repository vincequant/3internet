#!/bin/bash
# Fire the in-client D8 agent now, then verify on the host APPLICATION rows (L table).
# The DLL member list keeps the ghost on purpose, so it must not be used here.
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-fengye-lab/shadow"
NICK="${JOIN_NICKNAME:-待秋至}"
wpid() {
  WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-dingman-local" \
    "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tr -d '\r' | grep -E '^[0-9]+$' | tail -1
}
row_state() {
  # >0: 字面上只在「读到了主机 L 表且没有本昵称」时才算藏好。
  # 读不到（wine 噪音行 / 内存扫描失败）必须报 unreadable，绝不能当成「已藏」。
  local hp raw line
  hp=$(wpid); case "$hp" in ''|*[!0-9]*) echo unreadable; return ;; esac
  raw=$(WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-dingman-local" \
    SGI_BRIDGE_Z="$Z\\bridge" "$WINE" "$P32" -X utf8 "$S/tools/p32_app_rows_read.py" "$hp" 2>&1)
  line=$(printf '%s\n' "$raw" | grep '^{' | tail -1)
  [ -n "$line" ] || { echo unreadable; return; }
  printf '%s' "$line" | NICK="${NICK}" python3 -c '
import json,os,sys
try: d=json.loads(sys.stdin.read())
except Exception: print("unreadable"); raise SystemExit
names=[r.get("name") for t in d.get("tables",[]) for r in t.get("rows",[]) if r.get("id")]
print("present" if os.environ["NICK"] in names else "absent")
'
}
row_present() { [ "$(row_state)" = present ]; }
if [ "${1:-}" = "--check" ]; then
  st=$(row_state)
  echo "row_state=${st} (nick=${NICK})"
  [ "$st" = absent ] && exit 0 || exit 1
fi
echo "== hide now =="
for attempt in 1 2 3; do
  rm -f shadow_go.flag shadow_d8_receipt.bin
  bash inject.sh --force 2>&1 | tail -1
  bash fire.sh >/dev/null
  sleep 5
  [ -s shadow_d8_receipt.bin ] && xxd -l 8 shadow_d8_receipt.bin || echo "  attempt $attempt: no receipt"
  st=$(row_state)
  case "$st" in
    absent)
      echo "  attempt $attempt: row GONE from host L-table -> hidden"
      python3 - <<'PY2'
import json, time
open('shadow_hidden.json', 'w').write(json.dumps({
    'verified': True, 'at': time.time(), 'by': 'host_L_table',
    'note': 'application row gone on the host; DLL member row intentionally kept'}, ensure_ascii=False))
print('hidden marker written')
PY2
      exit 0 ;;
    present)
      echo "  attempt $attempt: host L-table still lists ${NICK}" ;;
    *)
      echo "  attempt $attempt: host L-table unreadable (not treated as hidden)" ;;
  esac
done
echo "!! still listed (or unreadable) after 3 attempts"; exit 1
