#!/bin/bash
# Resume script for the arm aborted at 2026-10-18 21:24 (resident install stage).
# Preconditions already in place (verified 21:30-21:35 from the host side):
#   - shadow client joined SGZWLB, 22 nullguard patches + 2 suppress sites applied
#   - D8 hide done: host app row removed, sync list back to 2 rows, DLL row retained
# This script runs ONLY the remaining steps: resident install(--bridge) -> capture
# -> start -> monitors -> Hub recorder -> auto-fire -> verify.
# No rejoin, no re-hide, no new member id. Mirrors arm_now.sh steps 5.5-8.
set -u
cd "$(dirname "$0")"
source ./_env.sh
echo "== R1) resident driver install (with --bridge core resolution) =="
rm -f shadow_round_c.flag shadow_round_c_receipt.bin
INST_OUT=$("$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action install \
    --target-name SANPK.exe --state "$Z\\inject-state-resident.json" \
    --flag "$Z\\shadow_round_c.flag" --receipt "$Z\\shadow_round_c_receipt.bin" \
    --bridge "$Z\\bridge" \
    --agent-bin "$Z\\tools\\resident-build\\shadow_resident.bin" 2>&1)
echo "$INST_OUT" | tail -1
if ! echo "$INST_OUT" | grep -q '"blob_addr"'; then echo "RESIDENT INSTALL FAILED - aborting resume"; exit 1; fi
RES_PID=$(python3 -c "import json;print(json.load(open('inject-state-resident.json'))['pid'])")
echo "resident pid (wine): $RES_PID"
mkdir -p "$HOME/sgi-protocol-lab-20260915/evidence/arm-resident"
"$WINE" "$P32" "$S/tools/shadow_stall_probe.py" --pid "$RES_PID" --state "$Z\\inject-state-resident.json" \
    --out "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\arm-resident" >/dev/null 2>&1
START_OUT=$("$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action start \
    --state "$Z\\inject-state-resident.json" \
    --recover-capture "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\arm-resident" 2>&1)
echo "$START_OUT" | tail -1
if ! echo "$START_OUT" | grep -q '"started": true'; then echo "RESIDENT START REFUSED (see above)"; fi
echo "== R2) slotkeep + watchers + RX + sampler =="
pkill -f "watch_peer.sh" 2>/dev/null || true
pkill -f "p33_host_watch" 2>/dev/null || true
pkill -f "shadow_slotkeep" 2>/dev/null || true
pkill -f "shadow_slotwatch" 2>/dev/null || true
pkill -f "rx_watch.py" 2>/dev/null || true
pkill -f "shadow_sampler" 2>/dev/null || true
pkill -f "stall_watchdog" 2>/dev/null || true
nohup bash slotkeep.sh --slot 1 --seconds 21600 --interval 0.25 --out "$Z\\logs\\slotkeep-test2.jsonl" >/dev/null 2>&1 &
nohup bash tools/watch_peer.sh host --duration 10800 --interval 1 --out "$Z\\logs\\hostwatch-test2.jsonl" >/dev/null 2>&1 &
nohup bash tools/watch_peer.sh shadow --duration 10800 --interval 1 --out "$Z\\logs\\shadowwatch-test2.jsonl" >/dev/null 2>&1 &
nohup bash slotwatch.sh --seconds 10800 --interval 0.5 --out "$Z\\logs\\slotwatch-test2.jsonl" >/dev/null 2>&1 &
nohup python3 rx_watch.py >/dev/null 2>&1 &
nohup python3 "$S/tools/stall_watchdog.py" 21600 >/dev/null 2>&1 &
nohup "$WINE" "$P32" "$S/shadow_sampler.py" --dir "$Z\\samples" --bridge "$Z\\bridge" --interval 30 --duration 10800 > logs/sampler.log 2>&1 &
echo "== R3) Hub session recorder =="
RSS=$(date +%Y%m%d-%H%M%S)
RSESS="$HOME/sgi-protocol-lab-20260915/fengye-hub-session/run-$RSS-shadow"
mkdir -p "$RSESS"
OWNID=$(python3 - <<'PY2'
import json, struct
own = 0
try:
    raw = open("shadow_d8_receipt.bin","rb").read(16)
    if raw[:4] == b"SHG2" and len(raw) >= 12:
        own = struct.unpack_from("<I", raw, 8)[0]
except Exception:
    own = 0
if not own:
    try:
        rows=[json.loads(l) for l in open("logs/host-arm.jsonl") if l.strip()]
        d=rows[-1]
        ids=[m["id"] for m in d["members"] if m["name"] in ("风夜","待秋至","小白")]
        own = ids[0] if ids else 0
    except Exception:
        own = 0
print(own)
PY2
)
echo "OWNID=$OWNID"
python3 - "$RSESS" "$OWNID" <<'PY2'
import json,sys
sess, own = sys.argv[1], int(sys.argv[2] or 0)
meta = {"mode":"shadow_observer","nickname":"风夜","phase":"room",
 "channel":{"own_id":own,"host_id":0,"transport":"NetHookCore/Koeinm","local_game_port":7777,"app_id":78731},
 "selected_room":{"op":"shadow","nickname":"风夜","session_name":"SGZWLB","host":"丁满","room_id":"","virtual_ip":""},
 "ghost_registered":True,"ghost_withdrawn":True,
 "note":"resumed arm (resident flow; 22+2 patches + suppress; D8 hide done 21:24)"}
open(sess+"/meta.json","w").write(json.dumps(meta, ensure_ascii=False, indent=1))
open(sess+"/state.json","w").write(json.dumps(meta, ensure_ascii=False))
print("meta written")
PY2
RSWIN="Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\fengye-hub-session\\$(basename "$RSESS")"
nohup "$WINE" "$P32" "$S/tools/shadow_session_rec.py" --session-dir "$RSWIN" --meta "$RSWIN\\meta.json" --interval 0.1 --chain-alias p1_directed_probe.py --line "多线3" > "$RSESS/recorder.log" 2>&1 &
echo $! > "$RSESS/recorder.pid"
python3 - "$RSESS" <<'PY2'
import json,sys,pathlib,time,shutil
sess=pathlib.Path(sys.argv[1])
home=pathlib.Path.home()/"sgi-protocol-lab-20260915/fengye-hub-session"
old=home/"active.json"
if old.exists():
    shutil.copy(old, home/("active.bak-resume-%d.json"%int(time.time())))
try:
    rpid=int((sess/"recorder.pid").read_text().strip())
except Exception:
    rpid=0
pointer={"id":sess.name,"directory":str(sess),"pid":rpid,"line":"多线3","started_at":time.time(),"kind":"shadow_observer"}
(home/"active.json").write_text(json.dumps(pointer, ensure_ascii=False))
print("active.json ->", sess.name, "pid", rpid)
PY2
echo "== R3.5) auto-fire watcher =="
pkill -f "shadow_auto_fire" 2>/dev/null || true
nohup python3 "$S/shadow_auto_fire.py" >/dev/null 2>&1 &
pkill -f "shadow_round_keeper" 2>/dev/null || true
echo "== R4) verify =="
sleep 2
pgrep -fl "shadow_slotkeep|watch_peer.sh|slotwatch.sh|rx_watch.py|shadow_session_rec|stall_watchdog|shadow_auto_fire" | sed 's/^/  /'
echo "-- d8 receipt --"; xxd -l 24 shadow_d8_receipt.bin 2>/dev/null
echo "-- resident check --"; "$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action check --state "$Z\\inject-state-resident.json" 2>&1 | tail -1 | cut -c1-400
echo "== RESUME DONE: resident installed+started, monitors+recorder+auto-fire up; ready for start =="
