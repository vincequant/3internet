#!/bin/bash
# P60 batch: arm N build commands on one client and fire them ALL in the same
# command phase (one trigger gesture -> N commands in the SAME round).
#
#   bash p60_multi_build.sh <actor> <prefix> type:x:y:extra [type:x:y:extra ...]
#   type 4 火计 / 5 落石 / 6 陷阱 / 7 练兵所 / 8 牧场 / 9 弓工坊
#   value(city id) 由 CITY 环境变量给（默认 5 = 平原）
#   example: bash p60_multi_build.sh 1 "$HOME/.../prefix-sikarugir10" 8:35:39:2000 9:35:41:2000
set -u
cd "$(dirname "$0")"
source ./_env.sh
ZS='Z:\Users\vk\sgi-fengye-lab\shadow'
ACTOR="${1:?actor force}"; PREFIX="${2:?wine prefix}"; shift 2
CITY="${CITY:-5}"
runpy() { local prefix="$1"; shift; WINEPREFIX="$prefix" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib" "$WINE" "$P32" "$@"; }
phase() { runpy "${HOST_PREFIX:-$PREFIX}" "$ZS\\tools\\roundprobe.py" --bridge "$ZS\\bridge" --samples 1 2>&1 | grep '^{' | tail -1 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('phase_4d8'))" 2>/dev/null; }
i=0
for spec in "$@"; do
  i=$((i+1)); IFS=':' read -r t x y ex <<< "$spec"
  runpy "$PREFIX" "$ZS\\tools\\p60_generic_cmd_inject.py" --force --preset build --actor "$ACTOR" \
    --build-type "$t" --x "$x" --y "$y" --value "$CITY" --extra "$ex" \
    --agent-bin "$ZS\\tools\\agent_generic.bin" --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
    --flag "$ZS\\p60_mi_$i.flag" --receipt "$ZS\\p60_mi_$i.bin" --state "$ZS\\p60_mi_$i.json" >/dev/null 2>&1
  echo "armed #$i type=$t @($x,$y) extra=$ex"
done
for i in $(seq 1 120); do P=$(phase); if [ "$P" = "1" ]; then sleep 2; [ "$(phase)" = "1" ] && break; fi; sleep 2; done
echo "phase 1 -> firing $(($#)) commands at once"
for i in $(seq 1 $#); do touch "p60_mi_$i.flag"; done
for i in $(seq 1 $#); do for k in $(seq 1 20); do sleep 0.3; [ -s "p60_mi_$i.bin" ] && break; done; done
python3 - "$#" <<'PY'
import struct,sys,os
n=int(sys.argv[1]); k='magic2 rc core own gb ga phase tick vt kind sub op f14 f18 f1c f20'.split()
ok=0
for i in range(1,n+1):
    p='p60_mi_%d.bin'%i
    if os.path.exists(p):
        d=dict(zip(k,struct.unpack('<16I',open(p,'rb').read(64))))
        print('#%d rc=%d type=%d city=%d extra=%d phase=%d xy=(%d,%d)' % (i,d['rc'],d['f18'],d['f1c'],d['f20'],d['phase'],d['op']&0xFFFF,(d['op']>>16)&0xFFFF))
        ok+=1
    else: print('#%d NO RECEIPT'%i)
print('receipts %d/%d' % (ok,n))
PY
