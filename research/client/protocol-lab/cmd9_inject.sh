#!/bin/bash
# Inject the P57 "ready" (cmd9) agent into the running shadow client, DORMANT.
# Fire it only if the host is visibly stuck waiting for the shadow's ready
# (i.e. the native 0x4635f3 reply did not happen):  bash cmd9_now.sh
set -u
source "$(dirname "$0")/_env.sh"
"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --target-name SANPK.exe \
  --agent-bin "$Z\\tools\\agent_cmd9.bin" --mode agent --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --flag "$Z\\shadow_cmd9_go.flag" --receipt "$Z\\shadow_cmd9_receipt.bin" --state "$Z\\inject-state-cmd9.json" "$@"
