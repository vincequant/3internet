#!/usr/bin/env bash
# P62 one D8 shot with before/after evidence.
#   p62_d8_shot.sh <outdir> <label> <departing_id>
# Reads the host app rows + ghost netobj, injects the P61 D8 agent (once per label),
# fires it via a flag file, then captures the receipt, host rows and host log text.
set -u
source "$HOME/sgi-fengye-lab/shadow/_env.sh"
S="$HOME/sgi-fengye-lab/shadow"
HOSTP="$HOME/Library/Application Support/SGI-Wine/prefix-dingman-local"
DL="$HOME/Library/Application Support/SGI-Wine/dependency-lib"
OUT="${1:?outdir}"; LABEL="${2:?label}"; DEP="${3:?departing id}"
mkdir -p "$OUT" "$S/p62"

win() { # win <prefix> <script> [args...]
  local prefix="$1" script="$2"; shift 2
  WINEPREFIX="$prefix" WINEDEBUG=-all DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" "$script" "$@" 2>&1
}

find_pid() {
  win "$1" "$S/tools/find_sanpk_pid.py" | tr -d '\r' | grep -E '^[0-9]+$' | tail -1
}

rows() { # rows <outfile>
  local hp; hp=$(find_pid "$HOSTP")
  if [ -z "$hp" ]; then echo '{"ok":false,"error":"host_pid_missing"}' > "$1"; return 1; fi
  WINEPREFIX="$HOSTP" WINEDEBUG=-all SGI_BRIDGE_Z="$Z\\bridge" \
    DYLD_FALLBACK_LIBRARY_PATH="$DL" "$WINE" "$P32" -X utf8 "$S/tools/p32_app_rows_read.py" "$hp" 2>&1 \
    | grep -a '^{' | tail -1 > "$1"
}

hosttext() { # hosttext <outfile>
  WINEPREFIX="$HOSTP" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" -X utf8 "$S/tools/read_text.py" '丁满' RichEdit 1500 2>&1 | tail -c 4000 > "$1" || true
}

echo "== shot ${LABEL} departing=${DEP} =="
rows "$OUT/rows-before.json"
FE_PID=$(find_pid "$WINEPREFIX")
echo "ghost_pid=${FE_PID}"
if [ -z "$FE_PID" ]; then echo "ghost pid missing"; exit 1; fi
win "$WINEPREFIX" "$S/tools/p62_netobj_probe.py" "$FE_PID" | grep -a '^{' | tail -1 > "$OUT/netobj.json"
cat "$OUT/netobj.json"; echo
hosttext "$OUT/hosttext-before.txt"

rm -f "$S/p62/$LABEL.flag" "$S/p62/$LABEL.bin"
win "$WINEPREFIX" "$S/tools/p61_d8_inject.py" \
  --departing "$DEP" \
  --agent-bin 'Z:\Users\vk\sgi-fengye-lab\shadow\tools\agent_d8.bin' \
  --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --flag "Z:\\Users\\vk\\sgi-fengye-lab\\shadow\\p62\\$LABEL.flag" \
  --receipt "Z:\\Users\\vk\\sgi-fengye-lab\\shadow\\p62\\$LABEL.bin" \
  --force > "$OUT/inject.txt" 2>&1
python3 - "$OUT/inject.txt" "$OUT/inject.json" <<'PYJ' || true
import json, sys, re
raw = open(sys.argv[1], encoding='utf-8', errors='replace').read()
i = raw.find('{')
try:
    obj, _ = json.JSONDecoder().raw_decode(raw[i:])
    open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(obj, ensure_ascii=False, indent=1))
    print({k: obj.get(k) for k in ('pid','koeinm','netobj','send','gethost','departing','frame_hex')})
except Exception as exc:
    print('inject-json-parse-failed:', exc)
PYJ

touch "$S/p62/$LABEL.flag"
sleep 5
if [ -s "$S/p62/$LABEL.bin" ]; then
  xxd "$S/p62/$LABEL.bin" > "$OUT/receipt.hex"; echo "receipt: $(xxd -p -l 20 "$S/p62/$LABEL.bin")"
else
  echo "no receipt"; fi
rows "$OUT/rows-after.json"
hosttext "$OUT/hosttext-after.txt"
echo "rows-before: $(cat "$OUT/rows-before.json")"
echo "rows-after : $(cat "$OUT/rows-after.json")"
echo "== done ${LABEL} =="
