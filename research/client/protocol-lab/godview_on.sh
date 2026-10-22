#!/bin/bash
# 手動開「全視野（去霧）」：15 個 p52 UI 元素 + 5 個 p53 開關（開局前有效，重開客戶端即消失）
set -u
SGI="$HOME/Library/Application Support/SGI-Wine"
SH="$HOME/sgi-fengye-lab/shadow"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"
cd "$SH" || exit 1
UISTATE="$Z\\ui-state-p52-$(date +%H%M%S).json"
n=0
for el in panel-create stat-12c stat-12d stat-12e stat-12f stat-130 stat-131 stat-132 cards-init cards-update map-tiles map-unit-sight map-unit-detail map-city-detail map-city-skin map-site-detail map-marker-detail; do
  "$WINE" "$P32" -X utf8 tools/p51_shadow_inject.py --mode ui --ui-action install --ui-element "$el" --state "$UISTATE" >/dev/null 2>&1 && n=$((n+1))
done
for el in map-trap-fire map-trap-rock map-trap-pit map-unit-sprites map-site-sprites; do
  "$WINE" "$P32" -X utf8 tools/p53_ui_control.py --action on --element "$el" >/dev/null 2>&1 && n=$((n+1))
done
python3 - "$n" <<'PY'
import json, sys, time
n = int(sys.argv[1]); 
open('/Users/vk/sgi-fengye-lab/shadow/shadow_godview.json','w').write(json.dumps(
    {'installed': n >= 15, 'elements': n, 'at': time.time()}, ensure_ascii=False))
print(json.dumps({'ok': n >= 15, 'elements': n}, ensure_ascii=False))
PY
