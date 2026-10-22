#!/bin/bash
# 進房後自動上補丁：nullguard + 開局守衛（跳 myforce）+ suppress 還原 + myforce 智能守衛
set -u
SGI="$HOME/Library/Application Support/SGI-Wine"
SH="$HOME/sgi-fengye-lab/shadow"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"

OUT=$(SKIP_D8=1 bash "$SH/sticky/sticky.sh" arm 2>&1)
PID=$(echo "$OUT" | grep -o '"pid": [0-9]*' | head -1 | grep -o '[0-9]*')
bash "$SH/suppress.sh" --revert >/dev/null 2>&1 || true
# 2026-10-22：面板跳過／元素回退會讓「指令」按不動，套用後立刻還原（保留 nullguard／開局守衛）
if [ -n "${PID:-}" ]; then
  "$WINE" "$P32" "$Z\\tools\\patch_panel_row_skip.py" "$PID" --revert >/dev/null 2>&1 || true
  "$WINE" "$P32" "$Z\\tools\\patch_element_fallback.py" "$PID" --revert >/dev/null 2>&1 || true
fi
GUARD=""
if [ -n "${PID:-}" ]; then
  GUARD=$("$WINE" "$P32" "$Z\\tools\\patch_myforce_guard.py" "$PID" 2>/dev/null | grep '^{' | tail -1 | cut -c1-120)
fi
# 綁定席位（預設 slot0，可用 SEAT 覆寫）＋ 摘席 D8
SEAT="${SEAT:-0}"
( nohup bash "$SH/slotkeep.sh" --slot "$SEAT" --seconds 21600 --interval 0.25 >/dev/null 2>&1 & )
sleep 4
bash "$SH/shadow_force.sh" switch "$SEAT" >/dev/null 2>&1 || true
SEATNOW=$(bash "$SH/shadow_force.sh" read 2>/dev/null | tail -1)
if [ "${KEEP:-0}" = "1" ]; then
  D8OUT='KEEP=1 → 不發 D8（保留名單，用於對照）'
else
  D8OUT=$(bash "$SH/sticky/sticky.sh" arm 2>&1 | tail -3)
fi
# 2026-10-22 保險：本一鍵鏈「不裝去霧」；若這個進程之前被裝過，只提示（執行期補丁無法卸載）
if [ -f "$SH/shadow_godview.json" ]; then
  echo "  ⚠ 這個客戶端已裝過去霧（全視野）；要恢復開局迷霧需重開客戶端" >&2
fi

RECEIPT="$SH/patch-receipt.json"
python3 - "$PID" "$(echo "$OUT" | tail -1)" "$GUARD" "$SEATNOW" "$D8OUT" "$RECEIPT" <<'PY'
import json, sys, time
pid, last, guard, seat, d8, receipt = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
hidden = 'D8 回執' in d8
payload = {'ok': bool(pid), 'pid': pid, 'arm': last[:90], 'myforce_guard': bool(guard),
           'seat': seat[:120], 'd8_hidden': hidden, 'd8': d8.replace(chr(10), ' ')[:120],
           'wall': time.strftime('%Y-%m-%dT%H:%M:%S')}
try:
    open(receipt, 'w', encoding='utf-8').write(json.dumps(payload, ensure_ascii=False))
except Exception:
    pass
print(json.dumps(payload, ensure_ascii=False))
PY
