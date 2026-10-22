#!/bin/bash
# 把風夜從房間帶回「游戏选择」：房內按取消 → 大廳確認「是」→ 必要時按啟動遊戲
set -u
SGI="$HOME/Library/Application Support/SGI-Wine"
SH="$HOME/sgi-fengye-lab/shadow"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"
ui(){ "$WINE" "$P32" "$Z\\tools\\_ui_quick.py" now >/dev/null 2>&1; }
title_at_browser(){ python3 - <<'PY'
import json,sys
try: d=json.load(open('/Users/vk/sgi-fengye-lab/shadow/sticky/ui-quick.json',encoding='utf-8'))
except Exception: sys.exit(1)
sys.exit(0 if any(w.get('title')=='游戏选择' and w.get('enabled') for w in d.get('windows',[])) else 1)
PY
}
ui; title_at_browser && { echo '{"ok": true, "state": "already-browser"}'; exit 0; }
"$WINE" "$P32" "$Z\\tools\\_dismiss.py" >/dev/null 2>&1
"$WINE" "$P32" "$Z\\tools\\click_text.py" '取消' >/dev/null 2>&1
sleep 3
"$WINE" "$P32" "$Z\\sticky\\hall_click.py" --window '三国志六网际网络增强版' --click '是' >/dev/null 2>&1
sleep 8
"$WINE" "$P32" "$Z\\tools\\_dismiss.py" >/dev/null 2>&1
ui
title_at_browser && { echo '{"ok": true, "state": "left-room"}'; exit 0; }
"$WINE" "$P32" "$Z\\sticky\\hall_click.py" --window '三国志六网际网络增强版' --click '启动游戏' >/dev/null 2>&1
sleep 10
"$WINE" "$P32" "$Z\\tools\\_dismiss.py" >/dev/null 2>&1
ui
title_at_browser && { echo '{"ok": true, "state": "started-game"}'; exit 0; }
echo '{"ok": false, "state": "stuck"}'
