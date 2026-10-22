#!/bin/bash
# 一鍵結束本機三個客戶端（丁满／风云／風夜）＋相關背景（slotkeep/監看/狀態），大廳保持不動
set -u
SGI="$HOME/Library/Application Support/SGI-Wine"
SH="$HOME/sgi-fengye-lab/shadow"
say(){ echo "[$(date +%H:%M:%S)] $*"; }
say "1) 停背景（slotkeep／launcher／狀態寫入）"
pkill -f launch_shadow_local 2>/dev/null
pkill -f shadow_slotkeep 2>/dev/null
pkill -f shadow_status.py 2>/dev/null
pkill -f slotwatch 2>/dev/null
pkill -f rx_watch.py 2>/dev/null
pkill -f retitle_game.py 2>/dev/null
sleep 1
say "2) 結束三個 SANPK（只關遊戲，大廳 SANGUO 不動）"
for p in $(pgrep -f 'SANPK\.exe'); do
  pre=$(lsof -p "$p" 2>/dev/null | grep -o 'prefix-dingman-local\|prefix-sikarugir10\|prefix-fengye-shadow' | head -1)
  if [ -n "$pre" ]; then
    kill -9 "$p" 2>/dev/null && say "   killed pid=$p ($pre)"
  fi
done
sleep 2
left=$(pgrep -f 'SANPK\.exe' | wc -l | tr -d ' ')
say "3) 剩餘 SANPK：$left"
pgrep -f 'SANGUO\.exe' >/dev/null && say "   大廳 SANGUO 仍在（保持）" || say "   大廳 SANGUO 未運行"
say "完成。"
