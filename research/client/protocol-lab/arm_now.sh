#!/bin/bash
# One-click arm (panel / CLI): stop -> launch+join -> roster -> patches(20) -> suppress
# -> D8 hide -> E agent (dormant, effect-verified) -> slotkeep+watchers+RX -> Hub recorder -> verify.
# Full SOP 2026-10-18 (post roundtest1/2): the C rounds agent is injected DORMANT;
# fire it only AFTER the shadow screen shows the match:  bash fire_round.sh
set -u
cd "$(dirname "$0")"
source ./_env.sh
JOIN_NAME="${JOIN_NAME:-SGZWLB}"
# 常駐版（2026-10-18 15:1x 定案）：預設無上限續跟（原 20）；如需舊行為：MAX_ROUNDS=20 bash arm_now.sh
# 2026-10-18 15:18 回退：無上限模式暫停（15:16 空轉事件：40 秒 2000+ 週期、進程 2k+ 執行緒）。
# 有界 200 ＋ keeper 自動續跟＝現行安全值；修好「防空轉閘」再評估無上限。
MAX_ROUNDS="${MAX_ROUNDS:-200}"
# 2026-10-18 23:2x 定案（用户：「Hub 进房也要装驱动器，必须完全一致」）：
# v2.1 驱动器（开局安全单驱动 + 回合间让路 1.5s）为武装默认；被动回退 USE_RESIDENT=0。
USE_RESIDENT="${USE_RESIDENT:-1}"
# 2026-10-19：無勢力旁觀為預設席位（5=空席）。舊預設 1＝借風雲席位（會顯示其勢力/倒計時）。
SEAT_SLOT="${SEAT_SLOT:-5}"
# 2026-10-19：進房暱稱（顯示名）可選，武裝前寫入影子客戶端配置（GBK）。房間名走 JOIN_NAME。
JOIN_NICKNAME="${JOIN_NICKNAME:-待秋至}"
echo "== 1) stop old session =="
bash stop_shadow.sh 2>&1 | tail -2
# 2026-10-19: drop stale receipts BEFORE anything reads them. The recorder derives
# own_id from shadow_d8_receipt.bin; a leftover receipt from an earlier run made
# the Hub report the wrong ghost id (seen live: 177451434 vs the real 173223220).
rm -f shadow_d8_receipt.bin shadow_cmd9_receipt.bin shadow_round_c_receipt.bin
rm -f shadow_hidden.json shadow_godview.json
# hard clean: stop_shadow.sh's heuristic can miss orphaned/frozen shadow SANPKs
for p in $(pgrep -f "SANPK.exe" 2>/dev/null); do
  if lsof -p "$p" 2>/dev/null | grep -q "prefix-fengye-shadow"; then
    echo "  killing leftover shadow SANPK pid=$p"; kill "$p" 2>/dev/null
  fi
done
sleep 2
echo "== 1.5) display name -> ${JOIN_NICKNAME} =="
JOIN_NICKNAME="$JOIN_NICKNAME" python3 - "$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/UserConfig.ini" "$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/Setting.ini" <<'PY2'
import os, shutil, sys
nick = os.environ.get('JOIN_NICKNAME') or '待秋至'
for path in sys.argv[1:]:
    try:
        raw = open(path, 'rb').read().decode('gbk', 'replace')
    except OSError:
        continue
    lines = raw.splitlines()
    changed = False
    for i, line in enumerate(lines):
        if line.strip().startswith('UserName='):
            lines[i] = 'UserName=' + nick
            changed = True
            break
    if changed:
        if not os.path.exists(path + '.bak-nick'):
            shutil.copy(path, path + '.bak-nick')
        open(path, 'wb').write('\r\n'.join(lines).encode('gbk', 'replace'))
        print('name set:', os.path.basename(path), '->', nick)
PY2
echo "== 2) launch + join =="
rm -f logs/app.log
open -n VKShadowLauncher.app --args --join-name "$JOIN_NAME"
ok=0
for j in $(seq 1 45); do
  sleep 3
  if grep -q '"event": "game_join", "ok": true' logs/app.log 2>/dev/null; then ok=1; break; fi
  if grep -q not_listed logs/app.log 2>/dev/null; then echo "NOT_LISTED（房间没挂牌）"; exit 1; fi
  if grep -q '"ev": "abort"' logs/app.log 2>/dev/null; then echo "ABORT（看 app.log）"; exit 1; fi
done
[ "$ok" = 1 ] || { echo "JOIN TIMEOUT"; exit 1; }
echo "JOINED"
sleep 3
echo "== 3) host roster =="
bash tools/watch_peer.sh host --duration 3 --interval 1 --out "$Z\\logs\\host-arm.jsonl" >/dev/null 2>&1
tail -1 logs/host-arm.jsonl | python3 -c 'import json,sys; d=json.loads(sys.stdin.readline()); print("members:", [(m["name"], m["id"]) for m in d.get("members", [])])' 2>/dev/null || true
echo "== 4) patches (nullguard 22) + suppress [verified gate] =="
verify_patches() {
  # $1 = mode name, $2 = minimum site count, $3 = raw output
  echo "$3" | tail -1
  echo "$3" | python3 -c "
import json, sys
mode = sys.argv[1]; need = int(sys.argv[2]); ok = False
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('{'): continue
    try: d = json.loads(line)
    except Exception: continue
    if d.get('mode') != mode: continue
    ps = d.get('patches', [])
    acts = set(p.get('action') for p in ps)
    ok = len(ps) >= need and acts <= {'applied', 'already'}
    print('%s: %d sites, actions %s' % (mode, len(ps), sorted(acts)))
sys.exit(0 if ok else 1)
" "$1" "$2" || { echo "PATCH VERIFY FAILED ($1) - aborting arm"; exit 1; }
}
NG_OUT=$(bash nullguard.sh 2>&1)
verify_patches nullguard 22 "$NG_OUT"
# 2026-10-19 20:0x：SUPPRESS=0 = 不抑制上行，风夜按「正常参与者」参与同步
# （要能真正影响战局必须走这条；抑制只用于纯旁观 + 本地驱动）
if [ "${SUPPRESS:-1}" = "1" ]; then
  SP_OUT=$(bash suppress.sh 2>&1)
  verify_patches suppress 2 "$SP_OUT"
else
  bash suppress.sh --revert 2>&1 | tail -1
  echo "  SUPPRESS=0 -> uplinks left alone (normal participant mode)"
fi
echo "== 5) D8 hide (verify on host roster, retry up to 3x) =="
if [ "${SKIP_D8:-0}" = "1" ]; then
  echo "  SKIP_D8=1 -> keep the member row for now (needed so the host sends the opening);"
  echo "  hide later with: bash hide_now.sh"
else
S="$HOME/sgi-protocol-lab-20260915/shadow"
row_present() {
  # Application rows (L table) only: the DLL member list legitimately keeps the
  # ghost after D8, so it must never be used to judge whether hiding worked.
  local wpid
  wpid=$(WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10" \
    "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tail -1)
  case "$wpid" in ''|ERR*) return 2 ;; esac
  WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10" \
    SGI_BRIDGE_Z="$Z\\bridge" "$WINE" "$P32" -X utf8 "$S/tools/p32_app_rows_read.py" "$wpid" 2>/dev/null \
    | tail -1 | python3 -c "
import json,sys
try: d=json.loads(sys.stdin.readline())
except Exception: sys.exit(2)
rows=[r for t in d.get('tables',[]) if t.get('table_hypothesis')=='L_pair_lower'
      for r in t.get('rows',[]) if r.get('id')]
names=[r.get('name') for r in rows]
sys.exit(0 if '${JOIN_NICKNAME}' in names else 1)
"
}
echo "-- wait for the host to list our row (max 20s) --"
for i in $(seq 1 10); do
  if row_present; then echo "  row visible: ${JOIN_NICKNAME}"; break; fi
  sleep 2
done
bash accept_inject.sh 2>&1 | tail -1
hide_ok=0
for attempt in 1 2 3; do
  rm -f shadow_go.flag shadow_d8_receipt.bin
  if [ "$attempt" = 1 ]; then bash inject.sh 2>&1 | tail -1; else bash inject.sh --force 2>&1 | tail -1; fi
  bash fire.sh >/dev/null
  sleep 5
  if [ -s shadow_d8_receipt.bin ]; then xxd -l 16 shadow_d8_receipt.bin; else echo "  attempt $attempt: no receipt"; fi
  if row_present; then
    echo "  attempt $attempt: host roster still lists ${JOIN_NICKNAME}"
  else
    echo "  attempt $attempt: row GONE from host roster -> hidden"; hide_ok=1; break
  fi
done
[ "$hide_ok" = 1 ] || echo "!! HIDE NOT VERIFIED (host roster still lists ${JOIN_NICKNAME}) — do not start the match yet"
[ "$hide_ok" = 1 ] || exit 1
python3 - <<'PY2'
import json, time
open('shadow_hidden.json', 'w').write(json.dumps({
    'verified': True, 'at': time.time(), 'by': 'host_L_table',
    'note': 'application row gone on the host; DLL member row intentionally kept'}, ensure_ascii=False))
print('hidden marker written')
PY2
fi
echo "== 5.2) cmd9 ready agent (dormant standby) =="
# 2026-10-19: keeping the seat row (SKIP_D8=1) makes the host send the opening
# snapshot, but the host also waits for our cmd9. The native client answers by
# itself (SANPK 0x4635f3 -> cmd9 after cmd7/8), so this agent stays dormant and
# is fired manually ONLY if the host is visibly stuck on "waiting for <nick>".
rm -f shadow_cmd9_go.flag shadow_cmd9_receipt.bin
bash cmd9_inject.sh 2>&1 | tail -1 | cut -c1-160
echo "== 5.5) resident driver (USE_RESIDENT=${USE_RESIDENT:-0}) =="
# v2.1 resident = opening-safe single driver + 1.5 s post-round dwell:
# spawner call 0x44474E and main-UI wait 0x44A8D9 stay ORIGINAL (v1 hooks broke
# the opening: AV 0x444786); native spawns are absorbed by the owner gate.
# Certified: unicorn 19/19 (both ends), real-df9b5225 byte checks, py32 compile.
# DEFAULT ON since 2026-10-18 23:2x (user: Hub arm path must be identical).
# Passive fallback: USE_RESIDENT=0 bash arm_now.sh
rm -f shadow_round_c.flag shadow_round_c_receipt.bin
if [ "${USE_RESIDENT:-0}" = "1" ]; then
INST_OUT=$("$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action install \
    --target-name SANPK.exe --state "$Z\\inject-state-resident.json" \
    --flag "$Z\\shadow_round_c.flag" --receipt "$Z\\shadow_round_c_receipt.bin" \
    --bridge "$Z\\bridge" \
    --agent-bin "$Z\\tools\\resident-build\\shadow_resident.bin" 2>&1)
echo "$INST_OUT" | tail -1
if ! echo "$INST_OUT" | grep -q '"blob_addr"'; then echo "RESIDENT INSTALL FAILED - aborting arm"; exit 1; fi
RES_PID=$(python3 -c "import json;print(json.load(open('inject-state-resident.json'))['pid'])")
mkdir -p "$HOME/sgi-protocol-lab-20260915/evidence/arm-resident"
"$WINE" "$P32" "$S/tools/shadow_stall_probe.py" --pid "$RES_PID" --state "$Z\\inject-state-resident.json" \
    --out "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\arm-resident" >/dev/null 2>&1
START_OUT=$("$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action start \
    --state "$Z\\inject-state-resident.json" \
    --recover-capture "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\arm-resident" 2>&1)
echo "$START_OUT" | tail -1
if ! echo "$START_OUT" | grep -q '"started": true'; then echo "RESIDENT START REFUSED (see above)"; fi
else
echo "SKIPPED: passive-observer config (22+2 patches + suppress + D8 hide + monitors); no round driver, no auto-fire."
fi
echo "== 5.6) god view (GODVIEW=${GODVIEW:-1}) =="
# 2026-10-18/19: fog lifted live via p52 map-tiles (tile-color renderer forced to
# the in-view palette); entity sprites via p53 C switches (mask 31); the info bar
# needs panel-create BEFORE the match panel is created -> install here, pre-start.
if [ "${GODVIEW:-1}" = "1" ]; then
  UISTATE="$Z\\ui-state-p52-$(date +%H%M%S).json"
  for el in panel-create stat-12c stat-12d stat-12e stat-12f stat-130 stat-131 stat-132 cards-init cards-update map-tiles map-unit-sight map-unit-detail map-city-detail map-city-skin map-site-detail map-marker-detail; do
    printf "  p52 %-18s " "$el"
    "$WINE" "$P32" -X utf8 tools/p51_shadow_inject.py --mode ui --ui-action install --ui-element "$el" --state "$UISTATE" 2>&1 | tail -1 | cut -c1-90
  done
  for el in map-trap-fire map-trap-rock map-trap-pit map-unit-sprites map-site-sprites; do
    printf "  p53 %-18s " "$el"
    "$WINE" "$P32" -X utf8 tools/p53_ui_control.py --action on --element "$el" 2>&1 | tail -1 | cut -c1-90
  done
  python3 - <<'PY2'
import json, time
open('shadow_godview.json', 'w').write(json.dumps({
    'installed': True, 'at': time.time(), 'elements': 22,
    'parts': ['全圖繪製', '部隊與城池圖示', '迷霧移除', '詳細資訊圖層']}, ensure_ascii=False))
print('godview marker written')
PY2
else
  echo "SKIPPED (GODVIEW=0)"
fi
echo "== 6) slotkeep + watchers + RX + sampler =="
pkill -f "watch_peer.sh" 2>/dev/null || true
pkill -f "p33_host_watch" 2>/dev/null || true
pkill -f "shadow_slotkeep" 2>/dev/null || true
pkill -f "shadow_slotwatch" 2>/dev/null || true
pkill -f "rx_watch.py" 2>/dev/null || true
pkill -f "shadow_sampler" 2>/dev/null || true
pkill -f "stall_watchdog" 2>/dev/null || true
if [ "${SEAT_SLOT}" = "skip" ]; then
  echo "  slotkeep SKIPPED (SEAT_SLOT=skip -> native my_slot; use while the seat row must stay for the opening)"
else
  nohup bash slotkeep.sh --slot "$SEAT_SLOT" --seconds 21600 --interval 0.25 --out "$Z\\logs\\slotkeep-test2.jsonl" >/dev/null 2>&1 &
fi
nohup bash tools/watch_peer.sh host --duration 10800 --interval 1 --out "$Z\\logs\\hostwatch-test2.jsonl" >/dev/null 2>&1 &
nohup bash tools/watch_peer.sh shadow --duration 10800 --interval 1 --out "$Z\\logs\\shadowwatch-test2.jsonl" >/dev/null 2>&1 &
nohup bash slotwatch.sh --seconds 10800 --interval 0.5 --out "$Z\\logs\\slotwatch-test2.jsonl" >/dev/null 2>&1 &
nohup python3 rx_watch.py >/dev/null 2>&1 &
nohup python3 "$S/tools/stall_watchdog.py" 21600 >/dev/null 2>&1 &
nohup "$WINE" "$P32" "$S/shadow_sampler.py" --dir "$Z\\samples" --bridge "$Z\\bridge" --interval 30 --duration 10800 > logs/sampler.log 2>&1 &
echo "== 7) Hub session recorder =="
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
python3 - "$RSESS" "$OWNID" <<'PY2'
import json,sys
sess, own = sys.argv[1], int(sys.argv[2] or 0)
meta = {"mode":"shadow_observer","nickname":"风夜","phase":"room",
 "channel":{"own_id":own,"host_id":0,"transport":"NetHookCore/Koeinm","local_game_port":7777,"app_id":78731},
 "selected_room":{"op":"shadow","nickname":"风夜","session_name":"SGZWLB","host":"丁满","room_id":"","virtual_ip":""},
 "ghost_registered":True,"ghost_withdrawn":True,
 "note":"panel-armed shadow session (20 patches + suppress; C agent dormant)"}
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
    shutil.copy(old, home/("active.bak-panel-%d.json"%int(time.time())))
# The hub judges session liveness as driver pid == pointer pid, so write the
# real recorder pid (recorder.pid holds the wine-launched python pid which is
# exactly what remote_snapshot.processes() reports).
try:
    rpid=int((sess/"recorder.pid").read_text().strip())
except Exception:
    rpid=0
pointer={"id":sess.name,"directory":str(sess),"pid":rpid,"line":"多线3","started_at":time.time(),"kind":"shadow_observer"}
(home/"active.json").write_text(json.dumps(pointer, ensure_ascii=False))
print("active.json ->", sess.name, "pid", rpid)
PY2
echo "== 7.2) live status writer (hub 狀態清單資料源) =="
pkill -f "shadow_status.py" 2>/dev/null || true
nohup "$WINE" "$P32" "$S/tools/shadow_status.py" \
  --session "$Z\\Users\\vkquant\\sgi-protocol-lab-20260915\\fengye-hub-session\\$(basename "$RSESS")" \
  --shadow "$Z" --samples "$Z\\samples" --bridge "$Z\\bridge" --interval 2 \
  > logs/status-writer.log 2>&1 &
echo "  status writer started"
echo "== 7.5) auto-fire watcher =="
pkill -f "shadow_auto_fire" 2>/dev/null || true
pkill -f "shadow_round_keeper" 2>/dev/null || true
if [ "${USE_RESIDENT:-0}" = "1" ]; then
nohup python3 "$S/shadow_auto_fire.py" >/dev/null 2>&1 &
else
echo "SKIPPED: no round driver in this config (auto-fire has no consumer)"
fi
echo "== 8) verify ==="
sleep 2
pgrep -fl "shadow_slotkeep|watch_peer.sh|slotwatch.sh|rx_watch.py|shadow_session_rec" | sed 's/^/  /'
echo "-- d8 receipt --"; xxd -l 16 shadow_d8_receipt.bin 2>/dev/null
if [ "${USE_RESIDENT:-0}" = "1" ]; then
echo "-- resident state (head) --"; head -12 inject-state-resident.json 2>/dev/null
echo "-- resident check --"; "$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action check --state "$Z\\inject-state-resident.json" 2>&1 | tail -1 | cut -c1-200
fi
echo "-- SUMMARY-EXT: new tools --"
ls -l "$S/tools/stall_watchdog.py" "$S/tools/chat_text_probe.py" "$S/tools/archive_evidence.py" 2>/dev/null | awk '{print "  ", $9}'
echo "-- SUMMARY-EXT: watch/lag freshness --"
for f in logs/lagwatch.jsonl logs/stall-watchdog.log logs/rx-watch.log; do
  if [ -f "$f" ]; then echo "  $f: $(wc -l < "$f") lines, mtime $(stat -f "%Sm" -t "%H:%M:%S" "$f")"; fi
done
if [ "${USE_RESIDENT:-0}" = "1" ]; then
echo "-- SUMMARY-EXT: resident counters --"
"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode resident --resident-action check --state "$Z\\inject-state-resident.json" 2>/dev/null | tail -1 | python3 -c "
import json,sys
try:
    d=json.loads(sys.stdin.readline())
    st=d.get('state',{})
    print('  installed:', d.get('installed'), '| main_tid:', st.get('main_tid'), '| blob:', st.get('blob_addr'))
except Exception as e:
    print('  (resident check unreadable)')
"
fi
if [ "${USE_RESIDENT:-0}" = "1" ]; then
echo "== ARM DONE: 风夜在房、22补丁+suppress、已藏身、常驻驱动器已装并启动（等开局帧后自动开始跟局）、监视+记录器在跑；可以按开始 =="
else
echo "== ARM DONE (passive): 风夜在房、22补丁+suppress、已藏身、监视+记录器在跑；无回合驱动器；可以按开始 =="
fi
