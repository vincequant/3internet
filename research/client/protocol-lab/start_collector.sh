#!/bin/bash
# 啟動 Hub 的資料來源（會話錄製器＋狀態寫入器），讓「勢力情報／指令」頁有資料
set -u
SGI="$HOME/Library/Application Support/SGI-Wine"
SH="$HOME/sgi-fengye-lab/shadow"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
export WINEPREFIX="$SGI/prefix-fengye-shadow" WINEDEBUG=-all PYTHONIOENCODING=utf-8
export DYLD_FALLBACK_LIBRARY_PATH="$SGI/dependency-lib"
WINE="$SGI/runtime-sikarugir10/wswine.bundle/bin/wine"
P32="$HOME/sgi-fengye-lab/python32/python.exe"
say(){ echo "[$(date +%H:%M:%S)] $*"; }

if pgrep -f shadow_session_rec.py >/dev/null 2>&1 && pgrep -f shadow_status.py >/dev/null 2>&1; then
  say "錄製器／狀態寫入器已在跑，不重複啟動"
  echo '{"ok": true, "state": "already"}'
  exit 0
fi

RSS=$(date +%Y%m%d-%H%M%S)
RSESS="$HOME/sgi-fengye-lab/fengye-hub-session/run-$RSS-shadow"
mkdir -p "$RSESS"
python3 - "$RSESS" <<'PY'
import json, sys
sess = sys.argv[1]
meta = {"mode": "shadow_observer", "nickname": "xiaolight", "phase": "room",
        "channel": {"own_id": 0, "host_id": 0, "transport": "NetHookCore/Koeinm",
                    "local_game_port": 7777, "app_id": 78731},
        "selected_room": {"op": "shadow", "nickname": "xiaolight", "session_name": "SGZWLB",
                          "host": "", "room_id": "", "virtual_ip": ""},
        "ghost_registered": True, "ghost_withdrawn": True,
        "note": "hub collector started by start_collector.sh"}
open(sess + "/meta.json", "w").write(json.dumps(meta, ensure_ascii=False, indent=1))
open(sess + "/state.json", "w").write(json.dumps(meta, ensure_ascii=False))
PY
RSWIN="Z:\\Users\\vk\\sgi-fengye-lab\\fengye-hub-session\\$(basename "$RSESS")"
nohup "$WINE" "$P32" "$SH/tools/shadow_session_rec.py" --session-dir "$RSWIN" --meta "$RSWIN\\meta.json" \
  --interval 0.1 --line "多线3" > "$RSESS/recorder.log" 2>&1 &
echo $! > "$RSESS/recorder.pid"
pkill -f shadow_status.py 2>/dev/null
nohup "$WINE" "$P32" "$SH/tools/shadow_status.py" --session "$RSWIN" --shadow "$Z" \
  --samples "$Z\\samples" --bridge "$Z\\bridge" --interval 2 > "$SH/logs/status-writer.log" 2>&1 &
python3 - "$RSESS" <<'PY'
import json, sys, pathlib, time
sess = pathlib.Path(sys.argv[1]); home = pathlib.Path.home() / 'sgi-fengye-lab/fengye-hub-session'
try: rpid = int((sess / 'recorder.pid').read_text().strip())
except Exception: rpid = 0
(home / 'active.json').write_text(json.dumps(
    {"id": sess.name, "directory": str(sess), "pid": rpid, "line": "多线3",
     "started_at": time.time(), "kind": "shadow_observer"}, ensure_ascii=False))
PY
sleep 3
say "已啟動：$RSESS"
echo '{"ok": true, "state": "started", "session": "'"$(basename "$RSESS")"'"}'
