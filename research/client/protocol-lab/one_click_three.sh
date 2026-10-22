#!/bin/bash
# 一鍵回測（2026-10-22 重寫）：風夜先起→建房→丁满/风云進房→補丁→綁定→D8 摘席
# 用法：bash one_click_three.sh [--no-hide] [--seat N] [--room SGZWLB]
# 全部用「已驗證可用」的路徑：
#   風夜啟動 = sticky.sh protocol-up（launch_shadow_local 會讓 SANPK exited，已棄用）
#   就緒判斷 = _ui_quick.py + JSON（win_probe 在部分 prefix 會靜默失敗）
set -u
SHADOW="$HOME/sgi-fengye-lab/shadow"
SGI="$HOME/Library/Application Support/SGI-Wine"
ROOM="SGZWLB"; HIDE=1; SEAT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-hide) HIDE=0 ;;
    --seat) SEAT="${2:?}"; shift ;;
    --room) ROOM="${2:?}"; shift ;;
    *) echo "unknown $1"; exit 2 ;;
  esac; shift
done
source "$SHADOW/_env.sh"
DL="$SGI/dependency-lib"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
P_DING="$SGI/prefix-dingman-local"
P_YUN="$SGI/prefix-sikarugir10"
P_YE="$SGI/prefix-fengye-shadow"
say(){ echo "[$(date +%H:%M:%S)] $*"; }

ui_now(){ # <prefix> → 先關掉 Delphi 模態（「沒有音效」等），再把視窗清單寫進 sticky/ui-quick.json
  WINEPREFIX="$1" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" "$Z\\tools\\_dismiss.py" >/dev/null 2>&1 || true
  WINEPREFIX="$1" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" "$Z\\tools\\_ui_quick.py" now >/dev/null 2>&1 || true
}
has_browser(){ ui_now "$1"; python3 - <<'PY'
import json,sys
try: d=json.load(open('/Users/vk/sgi-fengye-lab/shadow/sticky/ui-quick.json',encoding='utf-8'))
except Exception: sys.exit(1)
sys.exit(0 if any(w.get('title')=='游戏选择' and w.get('enabled') for w in d.get('windows',[])) else 1)
PY
}
has_room(){ ui_now "$1"; python3 - <<'PY'
import json,sys
try: d=json.load(open('/Users/vk/sgi-fengye-lab/shadow/sticky/ui-quick.json',encoding='utf-8'))
except Exception: sys.exit(1)
for w in d.get('windows',[]):
    if w.get('title','').startswith('三国志Internet联机版3.5') and '玩家名' in (w.get('texts') or []):
        sys.exit(0)
sys.exit(1)
PY
}
wait_for(){ # <prefix> <fn> <secs> <label>
  local pre="$1" fn="$2" lim="${3:-180}" t=0
  while :; do $fn "$pre" && return 0; t=$((t+4)); [ $t -ge "$lim" ] && { say "!! 等待逾時：$4（${lim}s）"; return 1; }; sleep 4; done
}
browser(){ local pre="$1"; shift; WINEPREFIX="$pre" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
  "$WINE" "$P32" "$Z\\tools\\game_browser.py" "$@" 2>&1 | grep '^{' | tail -1; }
kill_strays(){
  pkill -f launch_shadow_local 2>/dev/null
  for p in $(pgrep -f 'SANPK\.exe'); do
    lsof -p "$p" 2>/dev/null | grep -q "$1" && kill -9 "$p" 2>/dev/null
  done
}

say "0) 清場"
kill_strays prefix-dingman-local; kill_strays prefix-sikarugir10; kill_strays prefix-fengye-shadow
sleep 3

say "1) 丁满上線（房主）"
( cd "$HOME/sgi-direct-connect" && nohup ./run3.sh dingman > "$SHADOW/logs/oc3-dingman.log" 2>&1 & ) >/dev/null 2>&1
wait_for "$P_DING" has_browser 240 "丁满：游戏选择" || exit 1
say "   丁满 到游戏选择 ✓"

say "2) 丁满 建房：$ROOM"
browser "$P_DING" create "$ROOM"
sleep 4

say "3) 风云 上線並進房"
( cd "$HOME/sgi-direct-connect" && nohup ./run3.sh fengyun > "$SHADOW/logs/oc3-fengyun.log" 2>&1 & ) >/dev/null 2>&1
wait_for "$P_YUN" has_browser 240 "风云：游戏选择" || echo "   (风云 未到，繼續)"
browser "$P_YUN" join "$ROOM"
sleep 3

say "4) 風夜 上線並進房"
JOIN_NICKNAME="${SHADOW_NICK:-小白}" bash "$SHADOW/sticky/sticky.sh" protocol-up 2>&1 | tail -2
wait_for "$P_YE" has_browser 240 "風夜：游戏选择" || exit 1
browser "$P_YE" join "$ROOM"
sleep 4

say "5) 風夜 補丁"
ARM_OUT=$(SKIP_D8=1 bash "$SHADOW/sticky/sticky.sh" arm 2>&1)
echo "$ARM_OUT" | tail -2
bash "$SHADOW/suppress.sh" --revert >/dev/null 2>&1
# 2026-10-22：inject-state.json 會殘留舊 pid，改從 arm 輸出直接抓本次 SANPK pid
PID=$(echo "$ARM_OUT" | grep -o '"pid": [0-9]*' | head -1 | grep -o '[0-9]*')
[ -z "${PID:-}" ] && PID=$(python3 -c "import json;print(json.load(open('$SHADOW/inject-state.json'))['pid'])" 2>/dev/null || true)
if [ -n "${PID:-}" ]; then
  say "   myforce 智能守衛 pid=${PID}"
  WINEPREFIX="$P_YE" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" "$Z\\tools\\patch_myforce_guard.py" "$PID" 2>/dev/null | tail -1 | cut -c1-140
fi

if [ -n "$SEAT" ]; then
  say "6) 綁定席位 slot=$SEAT"
  ( nohup bash "$SHADOW/slotkeep.sh" --slot "$SEAT" --seconds 21600 --interval 0.25 >/dev/null 2>&1 & )
  sleep 4
  bash "$SHADOW/shadow_force.sh" switch "$SEAT" 2>&1 | tail -2
  bash "$SHADOW/shadow_force.sh" read 2>/dev/null | tail -1 | cut -c1-160
fi

if [ "$HIDE" = 1 ]; then
  say "7) D8 摘席"
  bash "$SHADOW/sticky/sticky.sh" arm 2>&1 | tail -3
fi

say "完成。"
