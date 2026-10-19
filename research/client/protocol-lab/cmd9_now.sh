#!/bin/bash
# Fire the in-client cmd9 ("ready") agent exactly once and decode the receipt.
#
# When to use: the shadow keeps its seat row (SKIP_D8=1) so the host sends the
# opening snapshot, but the host then hangs on "waiting for <nickname>" because
# it never received our cmd9. The native client normally answers by itself
# (SANPK 0x4635f3 replies cmd9 after a successful cmd7/cmd8); this agent is the
# standby for when it does not.
#
# Safety: one shot, no retry, target = host id, never self. The agent refuses
# when disconnected or when GetHostOrSelfID returns our own id.
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-protocol-lab-20260915/shadow"
rm -f shadow_cmd9_go.flag
if [ ! -s inject-state-cmd9.json ]; then
  echo "!! no cmd9 agent injected (arm_now.sh step 5.2 skipped?) - injecting now"
  bash cmd9_inject.sh 2>&1 | tail -1
fi
echo "== fire cmd9 (once) =="
rm -f shadow_cmd9_receipt.bin
touch shadow_cmd9_go.flag
for i in $(seq 1 20); do
  sleep 0.5
  [ -s shadow_cmd9_receipt.bin ] && break
done
if [ ! -s shadow_cmd9_receipt.bin ]; then
  echo "!! no receipt after 10s - agent not running or gated off (check inject-state-cmd9.json)"
  exit 1
fi
python3 - <<'PY'
import struct, time
raw = open('shadow_cmd9_receipt.bin', 'rb').read(24)
if len(raw) < 24 or raw[:4] != b'SHG9':
    print('!! unexpected receipt:', raw[:16].hex()); raise SystemExit(1)
rc, own, target, tick, last_len = struct.unpack_from('<IIIII', raw, 4)
print('cmd9 receipt: rc=%d own=0x%08x host=0x%08x tick=%d last_rx_len=%d' %
      (rc, own, target, tick, last_len))
print('  -> target is the host and differs from own: %s' % (target != own))
PY
echo "== host-side check (read-only, host prefix) =="
WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10" \
  "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tail -1
