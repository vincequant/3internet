#!/bin/bash
# Start the read-only hub recorder (+ live status writer) for the CURRENT shadow client.
# Extracted from arm_now.sh step 7.1/7.2 so it can be (re)started after a plain
# one_click_test.sh arming, which only does patches/suppress/hide/slot.
#
# Usage: bash start_hub_record.sh [--no-status]
set -u
cd "$(dirname "$0")"
source ./_env.sh
S="$HOME/sgi-fengye-lab/shadow"
HOME_HUB="$HOME/sgi-fengye-lab/fengye-hub-session"
mkdir -p "$HOME_HUB"
TS=$(date +%Y%m%d-%H%M%S)
RSESS="$HOME_HUB/run-${TS}-shadow"
mkdir -p "$RSESS"

OWNID=$(python3 - <<'PY'
import json
try:
    rows=[json.loads(l) for l in open("logs/host-arm.jsonl") if l.strip()]
    d=rows[-1]
    ids=[m["id"] for m in d["members"] if m["name"] in ("待秋至","风夜","小白")]
    print(ids[0] if ids else 0)
except Exception:
    print(0)
PY
)
python3 - "$RSESS" "$OWNID" <<'PY'
import json,sys
sess, own = sys.argv[1], int(sys.argv[2] or 0)
meta = {"mode":"shadow_observer","nickname":"待秋至","phase":"match",
 "channel":{"own_id":own,"host_id":0,"transport":"NetHookCore/Koeinm","local_game_port":7777,"app_id":78731},
 "selected_room":{"op":"shadow","nickname":"待秋至","session_name":"SGZWLB","host":"丁满","room_id":"","virtual_ip":""},
 "ghost_registered":True,"ghost_withdrawn":True,
 "note":"one_click_test arming (22 patches + suppress + D8 + slot5); read-only recorder"}
open(sess+"/meta.json","w").write(json.dumps(meta, ensure_ascii=False, indent=1))
open(sess+"/state.json","w").write(json.dumps(meta, ensure_ascii=False))
print("meta written own_id", own)
PY

RSWIN="Z:\\Users\\vk\\sgi-fengye-lab\\fengye-hub-session\\$(basename "$RSESS")"
nohup env PYTHONPATH="$Z\tools" "$WINE" "$P32" "$S/tools/shadow_session_rec.py" --session-dir "$RSWIN" --meta "$RSWIN\\meta.json" \
  --p33-dir "$Z\\tools" --interval 0.1 --chain-alias p1_directed_probe.py --line "多线3" > "$RSESS/recorder.log" 2>&1 &
echo $! > "$RSESS/recorder.pid"
echo "recorder pid=$(cat "$RSESS/recorder.pid") session=$RSESS"

python3 - "$RSESS" <<'PY'
import json,sys,pathlib,time,shutil
sess=pathlib.Path(sys.argv[1])
home=pathlib.Path.home()/"sgi-fengye-lab/fengye-hub-session"
old=home/"active.json"
if old.exists():
    shutil.copy(old, home/("active.bak-%d.json"%int(time.time())))
try: rpid=int((sess/"recorder.pid").read_text().strip())
except Exception: rpid=0
pointer={"id":sess.name,"directory":str(sess),"pid":rpid,"line":"多线3","started_at":time.time(),"kind":"shadow_observer"}
(home/"active.json").write_text(json.dumps(pointer, ensure_ascii=False))
print("active.json ->", sess.name, "pid", rpid)
PY

if [ "${1:-}" != "--no-status" ]; then
  pkill -f "shadow_status.py" 2>/dev/null || true
  nohup "$WINE" "$P32" "$S/tools/shadow_status.py" \
    --session "$RSWIN" --shadow "$Z" --samples "$Z\\samples" --bridge "$Z\\bridge" --interval 2 \
    > logs/status-writer.log 2>&1 &
  echo "status writer started pid=$!"
fi
