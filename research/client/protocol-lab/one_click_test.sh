#!/bin/bash
# 一键内测（本机三开）：丁满建房 → 风云进房 → 风夜进房＋补丁＋摘席
#
# 用法:
#   one_click_test.sh                # 全流程（清场 → 三开 → 建房/进房 → 补丁 → 摘席）
#   one_click_test.sh --skip-launch  # 沿用现有三台客户端，只做建房/进房/补丁/摘席
#   one_click_test.sh --room NAME    # 自定义房名（默认 SGZWLB）
#   one_click_test.sh --dry-run      # 只打印计划，不动任何东西
#
# 产物: shadow/logs/one_click-<ts>.log、shadow/one_click_state.json
# 注意: bash 3.2 下 "$VAR" 紧跟中文会解析错 → 本脚本统一用 ${VAR} 紧贴写法。
set -u

SHADOW="$HOME/sgi-fengye-lab/shadow"
SGI="$HOME/Library/Application Support/SGI-Wine"
ROOM="SGZWLB"
SKIP_LAUNCH=0
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-launch) SKIP_LAUNCH=1 ;;
    --room) ROOM="${2:?--room needs a name}"; shift ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

source "$SHADOW/_env.sh"
DL="$SGI/dependency-lib"
DINGMAN_PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-dingman-local"
FENGYUN_PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10"
FENGYE_PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow"
HOST_PREFIX="$DINGMAN_PREFIX"

TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$SHADOW/logs"
LOG="$SHADOW/logs/one_click-$TS.log"

say() { echo "[$(date +%H:%M:%S)] $*"; }

state() { # state <step> <status> [detail]
  python3 -c '
import json,sys,time
p=sys.argv[1]
d={}
try:
    d=json.load(open(p))
except Exception:
    pass
d.update({"at":time.time(),"step":sys.argv[2],"status":sys.argv[3]})
if len(sys.argv)>4 and sys.argv[4]:
    d["detail"]=sys.argv[4]
json.dump(d,open(p,"w"),ensure_ascii=False)
' "$SHADOW/one_click_state.json" "$1" "$2" "${3:-}"
}

# 防重入：用锁档（旧的 pgrep 判据会把上一轮遗留的壳当成“正在跑”，
# 2026-10-19 12:04 那轮的壳一直挂到 12:20，会把新一轮挡掉）
LOCK="$SHADOW/one_click.lock"
if [ -f "$LOCK" ]; then
  old=$(cat "$LOCK" 2>/dev/null)
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null && ps -p "$old" -o command= 2>/dev/null | grep -q 'one_click_test.sh'; then
    echo "已有另一个一键内测在跑（pid ${old}），退出"; exit 3
  fi
  echo "清理陈旧锁（pid ${old:-?} 已不在）"
  rm -f "$LOCK"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

if [ "$DRY" = 1 ]; then
  echo "== 一键内测（dry-run）计划 =="
  echo "0) 清场：结束三台旧客户端 + 残留对战大厅（--skip-launch 时跳过）"
  echo "1) 启动：丁满(prefix-dingman-local) / 风云(prefix-sikarugir10) / 风夜(prefix-fengye-shadow)"
  echo "2) 视窗标题：丁满 / 风云 / 待秋至"
  echo "3) 丁满建房「${ROOM}」；风云进房；风夜进房"
  echo "4) 风夜补丁 nullguard(22 站) + suppress(2 站)"
  echo "4b) 三台开局守卫（6 站，按开始之前；缺了会计时停住或直接退出）"
  echo "5) 风夜摘席 D8（幽灵从主机应用名册消失）"
  exit 0
fi

exec > >(tee -a "$LOG") 2>&1

say "== 一键内测 ${TS}（房名 ${ROOM}）=="
state launcher running

run_in() { # run_in <prefix> <z-script> [args...]
  # 2026-10-19 13:19 事故：这里原来是 `wine ... | grep`，只要有后台子壳继承了管道
  # 写端，grep 就永远等不到 EOF，整个脚本卡在「等待三个游戏选择」不报错也不超时。
  # 改成先落临时文件再过滤，彻底不经过管道。
  local prefix="$1" out rc; shift
  out=$(mktemp "${TMPDIR:-/tmp}/oneclick-XXXXXX")
  WINEPREFIX="$prefix" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" "$@" >"$out" 2>&1 </dev/null
  rc=$?
  grep -viE 'freetype|greater than|http|enable TrueType' "$out" || true
  rm -f "$out"
  return $rc
}

win_probe() { # win_probe <prefix> <title-substr>
  run_in "$1" "$Z\\tools\\win_probe.py" "$2" >/dev/null 2>&1
}

wait_window() { # wait_window <prefix> <substr> <timeout-s> <label>
  local t0
  t0=$(date +%s)
  while :; do
    win_probe "$1" "$2" && return 0
    if [ $(( $(date +%s) - t0 )) -ge "$3" ]; then
      say "  !! 等待逾时: $4"
      return 1
    fi
    sleep 3
  done
}

kill_sanguo() { # kill_sanguo <prefix>
  local prefix="$1" p
  for p in $(pgrep -f 'SANGUO\.exe' 2>/dev/null); do
    if lsof -p "$p" 2>/dev/null | grep -q "$prefix"; then
      say "  关闭残留对战大厅 SANPK-pid=${p} (${prefix})"
      kill "$p" 2>/dev/null
    fi
  done
}

start_retitle() { # start_retitle <prefix> <name> <tag>
  nohup env WINEPREFIX="$1" WINEDEBUG=-all PYTHONIOENCODING=utf-8 DYLD_FALLBACK_LIBRARY_PATH="$DL" \
    "$WINE" "$P32" "$Z\\tools\\retitle_game.py" "$2" >> "$SHADOW/logs/retitle-$3.log" 2>&1 </dev/null &
  echo $! > "$SHADOW/logs/retitle-$3.pid"
}

host_wine_pid() {
  # Wine 会往 stdout 混入「requires Wine version … or greater」等多行提示，
  # 用 tail -1 取到尾行的是提示而不是 pid（2026-10-19 12:05 实测名册读成 -1 的原因）。
  run_in "$DINGMAN_PREFIX" "$Z\\tools\\find_sanpk_pid.py" 2>/dev/null | tr -d '\r' | grep -E '^[0-9]+$' | tail -1
}

host_row_count() {
  local hp raw line
  hp=$(host_wine_pid)
  case "$hp" in ''|*[!0-9]*) echo -1; return ;; esac
  raw=$(WINEPREFIX="$DINGMAN_PREFIX" WINEDEBUG=-all PYTHONIOENCODING=utf-8 SGI_BRIDGE_Z="$Z\\bridge" \
    DYLD_FALLBACK_LIBRARY_PATH="$DL" "$WINE" "$P32" -X utf8 "$Z\\tools\\p32_app_rows_read.py" "$hp" 2>&1)
  # 只认真正的 JSON 行（同样避开杂讯行）
  line=$(printf '%s\n' "$raw" | grep '^{' | tail -1)
  if [ -z "$line" ]; then
    say "  (名册读取失败 pid=${hp}: $(printf '%s' "$raw" | tail -1 | cut -c1-120))"
    echo -1; return
  fi
  printf '%s' "$line" | python3 -c '
import json,sys
try:
    d=json.loads(sys.stdin.read())
except Exception:
    print(-1); raise SystemExit
n=0
for t in d.get("tables",[]):
    for r in t.get("rows",[]):
        if r.get("id"):
            n+=1
print(n)'
}

# ---- 0) 清场 ----
if [ "$SKIP_LAUNCH" = 0 ]; then
  say "0) 清场（结束残留客户端；另清对战大厅）"
  bash "$SHADOW/stop_all_games.sh" 2>&1 | sed 's/^/  /'
  kill_sanguo "$DINGMAN_PREFIX"
  kill_sanguo "$FENGYUN_PREFIX"
  kill_sanguo "$FENGYE_PREFIX"
  pkill -f 'retitle_game.py' 2>/dev/null || true
  sleep 3
else
  say "0) --skip-launch：保留现有客户端"
fi

# ---- 1) 三开 ----
if [ "$SKIP_LAUNCH" = 0 ]; then
  say "1) 启动三条链"
  # 子壳本身必须把 stdio 接到 /dev/null：否则它会一直握着 tee 的管道，
  # 主脚本跑完也退不掉（2026-10-19 12:04 那轮就是这样留下 4 个壳 + 1 个 tee）。
  ( cd "$HOME/sgi-fengye-lab/dingman-connect" && nohup ./run.sh dingman >"$SHADOW/logs/one_click-$TS-dingman.log" 2>&1 </dev/null & ) >/dev/null 2>&1 </dev/null
  ( cd "$HOME/sgi-direct-connect" && nohup ./run.sh fengyun >"$SHADOW/logs/one_click-$TS-fengyun.log" 2>&1 </dev/null & ) >/dev/null 2>&1 </dev/null
  ( cd "$SHADOW" && nohup python3 launch_shadow_local.py --hold-seconds 7200 >"$SHADOW/logs/one_click-$TS-fengye.log" 2>&1 </dev/null & ) >/dev/null 2>&1 </dev/null
  say "  已拉起；等待三个『游戏选择』画面（各最多 4 分钟）"
  fail=0
  wait_window "$DINGMAN_PREFIX" '游戏选择' 240 '丁满' || fail=1
  wait_window "$FENGYUN_PREFIX" '游戏选择' 240 '风云' || fail=1
  wait_window "$FENGYE_PREFIX" '游戏选择' 240 '风夜' || fail=1
  if [ "$fail" != 0 ]; then
    say "!! 有客户端未到『游戏选择』，请看 logs/one_click-$TS-*.log"
    state launch failed
    exit 1
  fi
else
  say "1) 沿用现有客户端（不重启）"
fi
say "  三台都到『游戏选择』✓"

# ---- 1.5) 标题 ----
say "1.5) 视窗标题"
pkill -f 'retitle_game.py' 2>/dev/null || true
start_retitle "$DINGMAN_PREFIX" '丁满' dingman
start_retitle "$FENGYUN_PREFIX" '风云' fengyun
start_retitle "$FENGYE_PREFIX" '待秋至' fengye
sleep 2

# ---- 2) 丁满建房 ----
state room running
say "2) 丁满建房（${ROOM}）"
if ! win_probe "$DINGMAN_PREFIX" '游戏选择'; then
  say "  丁满不在『游戏选择』，尝试回退"
  run_in "$DINGMAN_PREFIX" "$Z\\tools\\ui_click.py" '取消' >/dev/null 2>&1 || true
  sleep 2
  run_in "$DINGMAN_PREFIX" "$Z\\tools\\ui_click.py" '是' >/dev/null 2>&1 || true
  sleep 2
fi
out=$(run_in "$DINGMAN_PREFIX" "$Z\\tools\\game_browser.py" create "$ROOM")
echo "  $out"
case "$out" in
  *'"ok": true'*) : ;;
  *) say "!! 建房失败"; state room failed "$out"; exit 1 ;;
esac
sleep 2

# ---- 3) 风云进房 ----
say "3) 风云进房"
fy=0
for i in 1 2 3 4; do
  out=$(run_in "$FENGYUN_PREFIX" "$Z\\tools\\game_browser.py" join "$ROOM" --fallback '[丁满]')
  echo "  try$i: $out"
  case "$out" in
    *'"ok": true'*) fy=1; break ;;
    *'browser not found'*) say "  （风云不在游戏选择：视为已在房/其他画面）"; fy=1; break ;;
  esac
  sleep 3
done
[ "$fy" = 1 ] || say "!! 风云进房未确认（继续）"
sleep 2

# ---- 4) 风夜进房 ----
say "4) 风夜进房"
fe=0
for i in 1 2 3 4; do
  out=$(run_in "$FENGYE_PREFIX" "$Z\\tools\\game_browser.py" join "$ROOM" --fallback '[丁满]')
  echo "  try$i: $out"
  case "$out" in
    *'"ok": true'*) fe=1; break ;;
    *'browser not found'*) fe=1; break ;;
  esac
  sleep 3
done
if [ "$fe" != 1 ]; then
  say "!! 风夜进房失败"; state room failed; exit 1
fi
sleep 2

# ---- 5) 名册 ----
say "5) 主机名册检查"
rc_before=-1
for i in 1 2 3 4 5 6 7 8; do
  rc_before=$(host_row_count)
  if [ "$rc_before" -ge 3 ] 2>/dev/null; then break; fi
  sleep 2
done
say "  名册行数=${rc_before}（期待 3=丁满+风云+幽灵）"
if ! [ "$rc_before" -ge 3 ] 2>/dev/null; then
  say "!! 未见幽灵行（继续尝试补丁/摘席）"
fi

# ---- 6) 补丁 + 抑制 ----
state stealth running
say "6) 风夜补丁 nullguard（21 站）"
out=$(bash "$SHADOW/nullguard.sh" 2>&1 | grep -viE 'freetype|greater than|http|enable TrueType')
echo "$out" | tail -1 | cut -c1-500; echo
if echo "$out" | grep -q '"failed"'; then say "  !! 有失败站点，请看日志"; fi

say "6b) 风夜抑制 suppress（2 站）"
out=$(bash "$SHADOW/suppress.sh" 2>&1 | grep -viE 'freetype|greater than|http|enable TrueType')
echo "$out" | tail -1 | cut -c1-400; echo

# 开局计时卡在 0:00 的守卫只存在于进程内存。一键每次都是新进程，
# 必须在按「开始」之前装到丁满、风云、风夜三台，不能只装风夜。
say "6c) 三台开局守卫（6 站）"
guard_fail=0
patch_opening() {
  local label="$1" prefix="$2" pid line
  pid=$(run_in "$prefix" "$Z\\tools\\find_sanpk_pid.py" 2>/dev/null | tr -d '\r' | grep -E '^[0-9]+$' | tail -1)
  case "$pid" in
    ''|*[!0-9]*) say "  !! 找不到游戏进程 ${label}"; guard_fail=1; return ;;
  esac
  line=$(run_in "$prefix" "$Z\\tools\\patch_start_nulls.py" "$pid" --clear-lock 2>/dev/null | tr -d '\r' | grep '^{' | tail -1)
  say "  ${label} pid=${pid} ${line}"
  case "$line" in
    *'"ok": true'*|*'"ok":true'*|*'"already": true'*|*'"already":true'*) ;;
    *) guard_fail=1 ;;
  esac
}
patch_opening "丁满" "$DINGMAN_PREFIX"
patch_opening "风云" "$FENGYUN_PREFIX"
patch_opening "风夜" "$FENGYE_PREFIX"
if [ "$guard_fail" != 0 ]; then
  say "!! 开局守卫没装上，先不要按开始"
  state stealth failed "opening-guard"
  exit 1
fi

# ---- 6d) 元素查表型別安全回退（只给风夜）----
# 2026-10-19：旧的「查不到就回传容器」补丁是类型谎言，练兵的查表一旦落空，
# 容器会被当成元素用，稍后在对话框里炸 this=0xfffffXXX。
# 新补丁：恢复 NULL 语义 + 把 0x4195C4 的转换调用改道到 cave，
# 落空时回传「同容器里第一个通过同一动态转换的真实元素」。
say "6d) 风夜元素查表回退（类型安全）"
fe_pid=$(run_in "$FENGYE_PREFIX" "$Z\\tools\\find_sanpk_pid.py" 2>/dev/null | tr -d '\r' | grep -E '^[0-9]+$' | tail -1)
case "$fe_pid" in
  ''|*[!0-9]*) say "  !! 找不到风夜游戏进程"; state stealth failed "element-fallback-pid"; exit 1 ;;
esac
ef_line=$(run_in "$FENGYE_PREFIX" "$Z\\tools\\patch_element_fallback.py" "$fe_pid" 2>/dev/null | tr -d '\r' | grep '^{' | tail -1)
say "  element pid=${fe_pid} ${ef_line}"
case "$ef_line" in
  *'"ok": true'*|*'"ok":true'*) ;;
  *) say "!! 元素查表回退没装上"; state stealth failed "element-fallback"; exit 1 ;;
esac
# 19:26 实测：面板元素容器是空的（旁听实例从不建信息栏）→ 查表只会回 NULL，
# 0x4a3e1e `mov esi,[ebx+0x3c]` 直接炸。这里给三个活着的查表点补「真实元素」：
# 用游戏自己的 operator new(0x44) + ctor 0x485256 造一个同类型对象（vtable 0x50A4F8，
# +0x30/+0x38/+0x3C/+0x40 由基类 ctor 归零）并缓存复用。
pr_line=$(run_in "$FENGYE_PREFIX" "$Z\\tools\\patch_panel_row_fallback.py" "$fe_pid" 2>/dev/null | tr -d '\r' | grep '^{' | tail -1)
say "  panel-row pid=${fe_pid} ${pr_line}"
case "$pr_line" in
  *'"ok": true'*|*'"ok":true'*) ;;
  *) say "!! 面板行回退没装上"; state stealth failed "panel-row-fallback"; exit 1 ;;
esac

# ---- 7) 摘席 ----
say "7) 风夜摘席（D8）"
( cd "$SHADOW" && bash hide_now.sh ) 2>&1 | tail -8

# ---- 7.5) 开局前先占空席位 ----
# 2026-10-19 12:3x 实测：藏身（D8 删掉应用层行）后主机开局不再把开局包投给风夜，
# 而原生客户端要先有席位才能在“开始”那一刻接住开局包 → 必须「按开始之前」就占好空席。
# 07:06 那局能 mode=3 进图的差别就在这里（当时 slot=5 是开局前设好的）。
if [ -z "${SLOT:-}" ] && [ -f "$SHADOW/start-faction.json" ]; then
  SLOT=$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["slot"]))' "$SHADOW/start-faction.json" 2>/dev/null || true)
fi
SLOT="${SLOT:-5}"
say "7.5) 风夜先占空席位 slot=${SLOT}（开局前，保持隐身）"
slot_out=$(bash "$SHADOW/shadow_force.sh" switch "$SLOT" 2>&1 | grep -viE 'freetype|greater than|http')
echo "$slot_out" | tail -2
case "$slot_out" in
  *"slotkeep(${SLOT}) restarted"*) : ;;
  *) say "  !! 占席失败（见上）"; state stealth failed "slot"; exit 1 ;;
esac
sleep 2
if bash "$SHADOW/hide_now.sh" --check >/dev/null 2>&1; then
  say "  占席后复核：主机应用名册仍无风夜（隐身保持）✓"
else
  say "  !! 占席后风夜出现在主机应用名册 —— 中止"
  state stealth failed "slot-visible"
  exit 1
fi

rc_after=-1
for i in 1 2 3 4 5 6 7 8 9 10; do
  rc_after=$(host_row_count)
  if [ "$rc_after" = 2 ] 2>/dev/null; then break; fi
  sleep 2
done
say "  名册行数=${rc_after}（期待 2）"

say "8) 幽灵客户端存活检查"
# 只数真正的游戏进程：启动器的观察器命令行里也带 SANPK.exe（会多数一个）
n=$(ps -ax | grep -v grep | grep -c 'SANPK\.exe /1an')
say "  SANPK 进程数=${n}（期待 3）"

# 8.5) 幽灵 wine server 同源检查
# 2026-10-19 事故：影子 prefix 的 wineserver 一旦退出（当时被外部 kill 带崩），
# 风夜客户端会变成“孤儿进程”——窗口还在、进程还在，但任何新 wine 工具（改值台、
# 面板、探针）都枚举不到它，主机开局还会因“有人不应答”而取消。
GP_PID=$(WINEPREFIX="$FENGYE_PREFIX" WINEDEBUG=-all "$WINE" "$P32" "$Z\\tools\\find_sanpk_pid.py" 2>/dev/null | tr -d '\r' | grep -E '^[0-9]+$' | tail -1)
if [ -n "$GP_PID" ]; then
  say "  幽灵 wine server 同源 ✓（wine-pid=${GP_PID}）"
else
  say "  !! 幽灵与 wine server 失联（孤儿进程）：改值台/探针都会失效，需要重启风夜客户端"
  state stealth failed "ghost_orphan"
  exit 1
fi

hidden_ok=0
if [ "$rc_after" = 2 ] 2>/dev/null; then
  hidden_ok=1
elif [ "$rc_after" = -1 ] 2>/dev/null; then
  # 名册读不到时，用 hide_now.sh 当场写过的主机 L 表结论兜底（仍要求新鲜）
  if [ -s "$SHADOW/shadow_hidden.json" ] && [ "$SHADOW/shadow_hidden.json" -nt "$SHADOW/logs/one_click-${TS}.log" ]; then
    say "  !! 名册复核读不到（已重试 10 次），改以 hide_now 当场的主机 L 表结论为准"
    hidden_ok=1
  fi
fi

if [ "$hidden_ok" = 1 ]; then
  say "9) 把这一局接到情报台"
  if bash "$SHADOW/start_hub_record.sh"; then
    say "  情报台会话已接上"
  else
    say "  !! 情报台会话没接上（游戏准备不受影响）"
  fi
  say "== 完成：风夜已藏身，开局守卫已装，可以按游戏里的『开始』 =="
  state done ok "room=$ROOM rows=$rc_after"
else
  say "!! 摘席后名册仍有 $rc_after 行（期望 2），请看日志"
  state stealth failed "rows=$rc_after"
  exit 1
fi
say "日志: $LOG"
