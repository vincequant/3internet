#!/bin/bash
# 本機自動結束回合：偵測到「新階段」後等 N 秒，用遊戲自己的送出管線送 CSanInetPhaseEndCmd。
# 只作用在本機風夜；不改倒數、不動主機時間。用法：bash auto_end.sh [秒數=45] [--dry]
set -u
SH="$HOME/sgi-fengye-lab/shadow"
SGI="$HOME/Library/Application Support/SGI-Wine"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"
export SGI_GAME_EXE='C:\sgi\run-3.5\3I\SANPK.exe'
WAIT="${1:-45}"; DRY=0; [ "${2:-}" = "--dry" ] && DRY=1
say(){ echo "[$(date +%H:%M:%S)] $*"; }

phase_now(){
  python3 - <<'PY'
import json, os
try:
    home = os.path.expanduser('~/sgi-fengye-lab/fengye-hub-session')
    a = json.load(open(os.path.join(home, 'active.json'), encoding='utf-8'))
    st = json.load(open(os.path.join(a.get('directory',''), 'status.json'), encoding='utf-8'))
    print((st.get('scene') or {}).get('phase'))
except Exception:
    print('')
PY
}
force_now(){
  bash "$SH/shadow_force.sh" read 2>/dev/null | tail -1 | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print(''); raise SystemExit
sn=d.get('slot_now'); f=(d.get('slot_forces') or {}).get(str(sn))
print(f if isinstance(f,int) and f>0 else '')
"
}

say "自動結束啟動：每階段等 ${WAIT} 秒後送出「階段結束」（dry=${DRY}）"
last=""; t0=0
while :; do
  ph=$(phase_now)
  now=$(date +%s)
  if [ -n "${ph}" ] && [ "${ph}" != "${last}" ]; then
    last="${ph}"; t0=$now
    say "新階段 phase=${ph}，計時 ${WAIT} 秒"
  fi
  if [ -n "$last" ] && [ $((now - t0)) -ge "$WAIT" ]; then
    act=$(force_now)
    if [ -z "$act" ]; then say "沒有勢力（跳過）"; last=""; sleep 3; continue; fi
    if [ "$DRY" = "1" ]; then
      say "[dry] 會送 phaseend actor=${act}"
    else
      out=$("$WINE" "$P32" "$Z\\tools\\p60_generic_cmd_inject.py" --preset phaseend --actor "$act" \
            --ui-path --expect-actor "$act" --agent-bin "$Z\\tools\\resident-build\\shadow_resident.bin" 2>&1 | tail -2)
      say "送出 phaseend actor=${act} → $(echo "$out" | tr '\n' ' ' | cut -c1-160)"
    fi
    last=""; sleep 5
  fi
  sleep 3
done
