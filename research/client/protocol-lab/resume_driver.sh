#!/bin/bash
# Install + start the v2.1 resident round driver on the ALREADY RUNNING shadow.
#
# Why a separate script: arm_now.sh (with USE_RESIDENT=0) arms passively so the
# opening transition is untouched (roundtest1: a driver alive during the opening
# left the client on the pre-start screen). Once the shadow is inside the map we
# install the driver here; native spawns are then funnelled through the owner
# gate (single driver, no double-drive).
#
# Default: dwell 1500 ms between rounds (v2.1 patch_resident_v21 default).
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-protocol-lab-20260915/shadow"
rm -f shadow_round_c.flag shadow_round_c_receipt.bin
INST_OUT=$("$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action install \
    --target-name SANPK.exe --state "$Z\\inject-state-resident.json" \
    --flag "$Z\\shadow_round_c.flag" --receipt "$Z\\shadow_round_c_receipt.bin" \
    --bridge "$Z\\bridge" \
    --agent-bin "$Z\\tools\\resident-build\\shadow_resident.bin" 2>&1)
echo "$INST_OUT" | tail -1
if ! echo "$INST_OUT" | grep -q '"blob_addr"'; then echo "RESIDENT INSTALL FAILED"; exit 1; fi
RES_PID=$(python3 -c "import json;print(json.load(open('inject-state-resident.json'))['pid'])")
mkdir -p "$HOME/sgi-protocol-lab-20260915/evidence/arm-resident"
"$WINE" "$P32" "$S/tools/shadow_stall_probe.py" --pid "$RES_PID" --state "$Z\\inject-state-resident.json" \
    --out "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\arm-resident" >/dev/null 2>&1
START_OUT=$("$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action start \
    --state "$Z\\inject-state-resident.json" \
    --recover-capture "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\arm-resident" 2>&1)
echo "$START_OUT" | tail -1
if ! echo "$START_OUT" | grep -q '"started": true'; then
  echo "!! resident start refused (gate) - see message above; world will only follow if the native loop drives"
  exit 1
fi
pkill -f "shadow_round_keeper" 2>/dev/null || true
echo "resident driver running (hooks: v2, dwell 1500 ms)"
