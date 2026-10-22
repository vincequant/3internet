#!/bin/bash
# 風夜一鍵（本機）：確保上線 → 清單加入 → 補丁 → 綁定 slot → D8
# 用法：bash one_click_ghost.sh [--seat N] [--keep]   （--keep＝不 D8）
set -u
SH="$HOME/sgi-fengye-lab/shadow"
SEAT=0; HIDE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --seat) SEAT="${2:?}"; shift ;;
    --keep) HIDE=0; KEEP=1 ;;
    *) echo "unknown $1"; exit 2 ;;
  esac; shift
done
say(){ echo "[$(date +%H:%M:%S)] $*"; }

say "1) 確保風夜上線"
if ! pgrep -f 'SANPK\.exe' >/dev/null; then
  JOIN_NICKNAME="${SHADOW_NICK:-xiaolight}" bash "$SH/sticky/sticky.sh" protocol-up 2>&1 | tail -2
  sleep 20
fi

in_room(){ # 已經是房間畫面（玩家名/君主選択）就回 0
  WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow" WINEDEBUG=-all \
    PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib" \
    "$HOME/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine" \
    "$HOME/sgi-fengye-lab/python32/python.exe" 'Z:\Users\vk\sgi-fengye-lab\shadow\tools\_ui_quick.py' now >/dev/null 2>&1
  python3 - <<'PY2'
import json,sys
try: d=json.load(open('/Users/vk/sgi-fengye-lab/shadow/sticky/ui-quick.json',encoding='utf-8'))
except Exception: sys.exit(1)
for w in d.get('windows',[]):
    if '玩家名' in (w.get('texts') or []): sys.exit(0)
sys.exit(1)
PY2
}

say "2) 進房（已在房內就跳過）"
if in_room; then
  say "   已在房間畫面 → 跳過加入"
else
  JOIN=$(bash "$SH/join_now.sh")
  echo "$JOIN"
  case "$JOIN" in
    *'"ok": true'*) ;;
    *) say "!! 加入失敗，停止（不重試）"; exit 1 ;;
  esac
fi

say "3) 補丁＋綁定 slot $SEAT$([ "$HIDE" = 1 ] && echo '＋D8')"
if [ "$HIDE" = 1 ]; then
  SEAT="$SEAT" KEEP="${KEEP:-0}" bash "$SH/patch_now.sh" | tail -1
else
  SEAT="$SEAT" bash "$SH/patch_now.sh" --keep 2>/dev/null | tail -1 || SEAT="$SEAT" bash "$SH/patch_now.sh" | tail -1
fi
