#!/bin/bash
# 一行式實況：客戶端／UDP／席位／補丁／D8／全知情報（collector）
set -u
SH="$HOME/sgi-fengye-lab/shadow"
SGI="$HOME/Library/Application Support/SGI-Wine"
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"

clients=""; udp=0
for p in $(pgrep -f 'SANPK\.exe' 2>/dev/null); do
  if lsof -p "$p" 2>/dev/null | grep -q 'prefix-fengye-shadow'; then
    clients="$clients $p"
    lsof -nP -p "$p" -iUDP 2>/dev/null | grep -q ':8077' && udp=$((udp+1))
  fi
done
seat=$(bash "$SH/shadow_force.sh" read 2>/dev/null | tail -1)
python3 - "$clients" "$udp" "$seat" <<'PY'
import json, os, sys, time
clients, udp, seat_line = sys.argv[1].strip(), sys.argv[2], sys.argv[3]
seat = {}
try: seat = json.loads(seat_line)
except Exception: pass
sn = seat.get('slot_now'); forces = seat.get('slot_forces') or {}
mine = forces.get(str(sn)) if sn is not None else None
rec = {}
try: rec = json.load(open(os.path.expanduser('~/sgi-fengye-lab/shadow/patch-receipt.json'), encoding='utf-8'))
except Exception: pass
col = {}
try:
    home = os.path.expanduser('~/sgi-fengye-lab/fengye-hub-session')
    act = json.load(open(os.path.join(home, 'active.json'), encoding='utf-8'))
    col = json.load(open(os.path.join(act.get('directory',''), 'status.json'), encoding='utf-8'))
    col['_session'] = os.path.basename(act.get('directory',''))
except Exception: pass
link = col.get('link') or {}; scene = col.get('scene') or {}; pat = col.get('patches') or {}
op = (pat.get('opening') or {}).get('ok', 0) + (pat.get('guard') or {}).get('ok', 0)
tot = (pat.get('opening') or {}).get('total', 0) + (pat.get('guard') or {}).get('total', 0)
print('客戶端 : %s（UDP 8077: %s）' % (clients or '不在線', '✓' if udp else '✗'))
print('席位   : slot %s → 勢力 %s' % (sn, mine if mine not in (None, -1) else '未分配'))
print('補丁   : pid %s ｜ guard %s ｜ D8 %s ｜ %s' % (
    rec.get('pid') or '—', '✓' if rec.get('myforce_guard') else '✗',
    '✓' if rec.get('d8_hidden') else '✗', rec.get('wall') or ''))
print('全知   : %s ｜ 連線 %s ｜ %s／phase %s ｜ 席位 %s→%s ｜ 補丁 %s/%s ｜ 迷霧 %s' % (
    col.get('_session', '（未接）'), '✓' if link.get('connected') else '✗',
    '地圖' if scene.get('in_map') else '非地圖', scene.get('phase'),
    (col.get('seat') or {}).get('slot'), (col.get('seat') or {}).get('force'),
    op, tot, '原版' if col.get('fog_original') else '已去霧'))
PY
