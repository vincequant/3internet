#!/bin/bash
# Open the unit card (edit panel) for the running shadow client.
# Must run inside the user's GUI session (launching it over plain ssh fails with
# WinError 1400 because macOS denies window creation to background sessions):
# use the desktop "開啟風夜改值面板.command" or
#   osascript -e 'tell application "Terminal" to do script "bash <this file>"'
#
# 2026-10-19: 预检「影子客户端是否还在本 prefix 的 wine server 里」。
# 现象：影子客户端会变成“孤儿”（进程还活着、窗口还在，但 wineserver 已不是
# 原来那个）→ 任何新起的 wine 工具（含本面板）都枚举不到它，只会反复打印
# “need exactly one shadow SANPK process”。这时唯一出路是重启影子客户端。
set -u
cd "$(dirname "$0")"
source ./_env.sh
TS=$(date +%Y%m%d-%H%M%S)
OUT="$Z\\logs\\p53-inspector-$TS.jsonl"

PRE=$(WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow" \
  "$WINE" "$P32" "$S/tools/find_sanpk_pid.py" 2>/dev/null | tr -d '\r' | tail -1)
case "$PRE" in
  ''|ERR*)
    echo "⛔ 影子客户端与 wine server 失联（枚举结果：${PRE:-空}）。"
    echo "   进程/窗口可能还在，但新的 wine 工具接管不了它 → 需要重启影子客户端（大厅会有一次进出记录）。"
    echo "   排查：pgrep -f 'SANPK.exe'; lsof -p <影子 mac pid> | grep server-；再比对 prefix 目录的 inode。"
    exit 2 ;;
esac
echo "影子 SANPK wine-pid=${PRE} ✓  wine server 同源"
echo "log: $OUT"
exec "$WINE" "$P32" -X utf8 tools/p53_unit_inspector.py --bridge "$Z\\bridge" --out "$OUT"
