#!/bin/bash
# 從「游戏选择」清單加入第一個房間（先關模態），輸出最後一行 JSON
set -u
SGI="$HOME/Library/Application Support/SGI-Wine"
SH="$HOME/sgi-fengye-lab/shadow"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"
"$WINE" "$P32" "$Z\\tools\\_dismiss.py" >/dev/null 2>&1 || true
LIST=$("$WINE" "$P32" "$Z\\tools\\game_browser.py" list 2>&1 | grep '^{' | tail -1)
HOST=$(echo "$LIST" | python3 -c "
import json,sys,re
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
items=d.get('items') or []
if not items:
    print(''); sys.exit(0)
m=re.search(r'\[([^\]]+)\]$', items[0])
print(m.group(1) if m else items[0])
")
if [ -z "$HOST" ]; then echo '{"ok": false, "error": "清單裡沒有房間（先在遊戲裡刷新列表）"}'; exit 0; fi
"$WINE" "$P32" "$Z\\tools\\game_browser.py" join "$HOST" 2>&1 | grep '^{' | tail -1
