#!/bin/bash
# Forge ONE command as ourselves: inject the uplink agent, fire it once, decode the receipt.
#
# This does NOT touch the seat/slot and does not need a faction: the host accepts
# the frame from our member id (it does not validate the actor field), which is
# the P46 finding. Exactly one frame per fire; no retry.
#
# Usage: bash p57_forge_upload.sh <payload-hex> [--force]
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-protocol-lab-20260915/shadow"
HEX="${1:?payload hex (no spaces)}"
MODE="${MODE:-uplink}"          # uplink = to host (reliable) | bcast = to all members (0x100023a0)
FORCE="${2:-}"
STATE="inject-state-$MODE.json"
if [ -f "$STATE" ] && [ "$FORCE" != "--force" ]; then
  echo "!! an uplink agent already exists ($STATE). Use --force to replace it (old one is spent)."
  exit 1
fi
rm -f shadow_uplink_go.flag shadow_uplink_receipt.bin
"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --target-name SANPK.exe --mode uplink \
  --agent-bin "$Z\\tools\\agent_$MODE.bin" --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --payload-hex "$HEX" --flag "$Z\\shadow_uplink_go.flag" \
  --receipt "$Z\\shadow_uplink_receipt.bin" --state "$Z\\$STATE" $FORCE \
  ${SPOOF_ID:+--spoof-id $SPOOF_ID} 2>&1 | tail -1 | cut -c1-200
sleep 1
touch shadow_uplink_go.flag
for i in $(seq 1 24); do sleep 0.5; [ -s shadow_uplink_receipt.bin ] && break; done
if [ ! -s shadow_uplink_receipt.bin ]; then
  echo "!! no receipt after 12s (agent gated off: disconnected / host==self / already sent)"
  exit 1
fi
python3 - <<'PY'
import struct
raw = open('shadow_uplink_receipt.bin', 'rb').read(24)
magic, rc, own, target, tick, ln = struct.unpack('<IIIIII', raw)
print('receipt magic=%08x rc=%d own=%d host=%d len=%d' % (magic, rc, own, target, ln))
print('  emitted exactly one reliable frame (to host)' if magic == 0x37474853 else
      '  emitted exactly one broadcast frame (to all members)' if magic == 0x38474853 else
      '  emitted exactly one frame with a swapped sender id' if magic == 0x39474853 else
      '  !! unexpected receipt')
PY
