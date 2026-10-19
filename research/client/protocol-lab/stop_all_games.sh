#!/bin/bash
# stop_all_games.sh - End the game clients of all three accounts if running:
#   fengyun (prefix-sikarugir10, via the launcher's game-stop: keeps hall + state)
#   dingman (prefix-dingman-local, prefix-scoped SIGTERM)
#   fengye/shadow (prefix-fengye-shadow, prefix-scoped SIGTERM)
# The hall is preserved. Idempotent. --dry-run prints instead of killing.
# hold/helper processes notice the SANPK exit and wind themselves down.
set -u
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

HOME_DIR="$HOME"
LAUNCHER="$HOME_DIR/Documents/Coding/三国志internet/scripts/sgi_wine_launcher.py"

find_pids_by_prefix() {
  local prefix="$1" p envp best
  for p in $(pgrep -f 'SANPK\.exe /1an' 2>/dev/null); do
    # 1) 最可靠：进程自身环境里的 WINEPREFIX
    envp=$(ps eww -p "$p" 2>/dev/null | tr ' ' '\n' | sed -n 's/^WINEPREFIX=//p' | head -1)
    if [ -n "$envp" ]; then
      case "$envp" in *"$prefix"*) echo "$p" ;; esac
      continue
    fi
    # 2) 退路：按该进程打开的 prefix 相关文件数取最多的那一个。
    #    （旧写法只要「任意一个文件命中」就算，Wine 进程会同时碰别的 prefix，
    #     2026-10-19 12:04 出现过把丁满/风夜标签互相打错。）
    best=$(lsof -p "$p" 2>/dev/null | grep -o 'SGI-Wine/prefix-[a-z0-9-]*' | sort | uniq -c | sort -rn | head -1)
    case "$best" in *"$prefix"*) echo "$p" ;; esac
  done
}

kill_scope() {
  local prefix="$1" label="$2" pids p
  pids=$(find_pids_by_prefix "$prefix")
  if [ -z "$pids" ]; then
    echo "  ${label}: no game running"
    return 0
  fi
  for p in $pids; do
    if [ "$DRY" = 1 ]; then
      echo "  ${label}: would kill SANPK pid=$p ($prefix)"
    else
      echo "  ${label}: killing SANPK pid=$p"
      kill "$p" 2>/dev/null
    fi
  done
}

echo "== end game clients (hall preserved) =="
if [ "$DRY" = 1 ]; then
  echo "  fengyun: dry-run (launcher game-stop skipped)"
else
  PY=/opt/homebrew/bin/python3
  [ -x "$PY" ] || PY=/usr/bin/python3
  if [ -f "$LAUNCHER" ]; then
    "$PY" -u "$LAUNCHER" game-stop 2>&1 | tail -1 | sed 's/^/  fengyun: /'
  else
    echo "  fengyun: launcher script not found, falling back to prefix kill"
  fi
fi
kill_scope "prefix-dingman-local" "dingman"
kill_scope "prefix-fengye-shadow" "fengye"

# safety net: fengyun SANPK still alive after game-stop (launcher failure path)
if [ "$DRY" = 1 ]; then
  kill_scope "prefix-sikarugir10" "fengyun(fallback)"
else
  leftover=$(find_pids_by_prefix "prefix-sikarugir10")
  [ -n "$leftover" ] && kill_scope "prefix-sikarugir10" "fengyun(fallback)"
fi

if [ "$DRY" = 0 ]; then
  sleep 2
  for prefix in prefix-sikarugir10 prefix-dingman-local prefix-fengye-shadow; do
    for p in $(find_pids_by_prefix "$prefix"); do
      echo "  force-killing leftover SANPK pid=$p ($prefix)"
      kill -9 "$p" 2>/dev/null
    done
  done
  echo "遊戲已結束，大廳保持運行。"
else
  echo "(dry-run: nothing killed)"
fi
