#!/bin/bash
# 本机「风夜（影子）」采集桥：在 prefix-fengye-shadow 里起第二座只读桥（端口 8771）。
# 与主源 Mac · VKQUANT（8769，管风云）并存；Hub 的「游戏数据源」选「Mac · 风夜（本机影子）」。
set -u
cd "$(dirname "$0")" || exit 1
HUB="$(pwd)"
WINE="/Users/vk/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine"
PREFIX="/Users/vk/Library/Application Support/SGI-Wine/prefix-fengye-shadow"
PORT="${SGI_BRIDGE_PORT:-8771}"

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "桥已在运行：http://127.0.0.1:$PORT/health"
  exit 0
fi
mkdir -p logs
printf '正在起本机风夜采集桥（端口 %s，只读 prefix-fengye-shadow）…\n' "$PORT"
WINEPREFIX="$PREFIX" WINEDEBUG=-all PYTHONIOENCODING=utf-8 \
  SGI_SOURCE_ID="FENGYE-LOCAL" SGI_BRIDGE_PORT="$PORT" SGI_BRIDGE_REMOTE_PORT=$((PORT+1)) \
  DYLD_FALLBACK_LIBRARY_PATH="/Users/vk/Library/Application Support/SGI-Wine/dependency-lib" \
  nohup "$WINE" "$HUB/bridge/python/python.exe" -B -c \
  'import pathlib,runpy,sys; runpy.run_path(str(pathlib.Path(sys.executable).resolve().parent.parent / "windows_bridge.py"),run_name="__main__")' \
  > logs/bridge-fengye.log 2>&1 &
sleep 8
curl -s --max-time 4 "http://127.0.0.1:$PORT/health" | head -c 200; echo
echo "日志：$(pwd)/logs/bridge-fengye.log"
