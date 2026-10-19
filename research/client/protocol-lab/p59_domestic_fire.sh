#!/bin/bash
# P59 one-shot: fire ONE interface-free CSanInetDomesticCmd (kind 18 training).
#
#   bash p59_domestic_fire.sh <actor_force> [parameter] [value] [extra]
#
#    parameter 0=infantry 1=cavalry 2=archer   (default 1)
#    value     kind-18 value operand          (default 95 = the only observed
#              real training command's value; see the P59 notes)
#    extra     kind-18 extra operand          (default 0)
#
# What it does (and does NOT do):
#   * arms a once-only agent inside the shadow SANPK (no UI, no view switch);
#   * the agent builds the command with the game's own ctor and calls the
#     game's own send path exactly once when the trigger file appears;
#   * nothing is retried; a receipt is written; the agent then sleeps forever.
#   * it does NOT change the seat/view, does not touch the host, does not
#     write the game EXE/save.
#
# Environment knobs:
#   PLAN=1     -> print the injector plan only (no write, no fire)
#   CHECK=1    -> print readback of receipt/state only
#   BEFORE=1   -> also dump the target force's training values before firing
#   FORCE=1    -> replace a stale arm/receipt of the same process
#   PID=...    -> override the auto-detected shadow SANPK pid
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-fengye-lab/shadow"
ACTOR="${1:?usage: p59_domestic_fire.sh <actor_force> [parameter] [value] [extra]}"
PARAM="${2:-1}"
VALUE="${3:-95}"
EXTRA="${4:-0}"
Z_FLAG="$Z\\p59_go.flag"
Z_RCPT="$Z\\p59_receipt.bin"
Z_STATE="$Z\\p59_state.json"
runpy() { "$WINE" "$P32" "$@"; }
FORCEARG=""
[ "${FORCE:-0}" = "1" ] && FORCEARG="--force"

if [ "${PLAN:-0}" = "1" ]; then
  runpy "$S/tools/p59_domestic_inject.py" --plan \
    --agent-bin "$Z\\tools\\agent_domestic.bin" \
    --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
    --actor "$ACTOR" --parameter "$PARAM" --value "$VALUE" --extra "$EXTRA" \
    --flag "$Z_FLAG" --receipt "$Z_RCPT" --state "$Z_STATE" $FORCEARG
  exit $?
fi

if [ "${CHECK:-0}" = "1" ]; then
  runpy "$S/tools/p59_domestic_inject.py" --check \
    --agent-bin "$Z\\tools\\agent_domestic.bin" \
    --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
    --actor "$ACTOR" --parameter "$PARAM" --value "$VALUE" --extra "$EXTRA" \
    --flag "$Z_FLAG" --receipt "$Z_RCPT" --state "$Z_STATE"
  exit $?
fi

PID="${PID:-$(pgrep -f 'prefix-fengye-shadow.*SANPK.exe' | head -1)}"
if [ -z "$PID" ]; then
  echo "!! cannot find the shadow SANPK on the macOS side (pgrep); set PID=<wine pid>"
  exit 2
fi
if [ "${BEFORE:-0}" = "1" ]; then
  echo "--- training snapshot BEFORE (wine pid $PID) ---"
  runpy "$S/tools/lord_read_any.py" "$PID" | tail -1
fi

rm -f p59_go.flag p59_receipt.bin
runpy "$S/tools/p59_domestic_inject.py" \
  --agent-bin "$Z\\tools\\agent_domestic.bin" \
  --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --actor "$ACTOR" --parameter "$PARAM" --value "$VALUE" --extra "$EXTRA" \
  --flag "$Z_FLAG" --receipt "$Z_RCPT" --state "$Z_STATE" $FORCEARG 2>&1 | tail -25
rc=$?
if [ $rc -ne 0 ]; then echo "!! injector failed rc=$rc (nothing fired)"; exit $rc; fi

sleep 1
touch p59_go.flag            # the one and only fire signal
for i in $(seq 1 30); do sleep 0.5; [ -s p59_receipt.bin ] && break; done
if [ ! -s p59_receipt.bin ]; then
  echo "!! no receipt after 15s — agent gated off (disconnected / no core / bad slot / already sent)"
  exit 1
fi
python3 - <<'PY'
import struct
raw = open('p59_receipt.bin', 'rb').read(48)
keys = ('magic2 rc core actor parameter value extra tick gate_before gate_after phase own').split()
vals = struct.unpack('<12I', raw)
r = dict(zip(keys, vals))
ok = r['magic2'] == 0x43523553
print('receipt magic=%08x %s' % (r['magic2'], 'OK' if ok else 'UNEXPECTED'))
print('  rc=%d (1 = SendCmd accepted)  core=0x%x  own=%d' % (r['rc'], r['core'], r['own']))
print('  command: actor=%d parameter=%d value=%d extra=%d' % (r['actor'], r['parameter'], r['value'], r['extra']))
print('  gate before/after = %d/%d (must be equal: we bypass 0x446482)' % (r['gate_before'], r['gate_after']))
print('  phase=%d tick=%d' % (r['phase'], r['tick']))
PY
[ "${AFTER:-0}" = "1" ] && { echo "--- training snapshot immediately AFTER (same turn) ---"; runpy "$S/tools/lord_read_any.py" "$PID" | tail -1; }
echo "--- now have the host end the round, then re-read ---"
echo "    wine python.exe $S/tools/lord_read_any.py $PID"
