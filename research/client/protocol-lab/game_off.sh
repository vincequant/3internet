#!/bin/bash
# 只關「遊戲」（SANPK），保留大廳與協議會話 → 下次一鍵登入可直接再進
set -u
say(){ echo "[$(date +%H:%M:%S)] $*"; }
n=0
for p in $(pgrep -f 'SANPK\.exe' 2>/dev/null); do
  if lsof -p "$p" 2>/dev/null | grep -q 'prefix-fengye-shadow'; then
    kill -9 "$p" 2>/dev/null && { say "關閉遊戲 pid=$p"; n=$((n+1)); }
  fi
done
pkill -f shadow_slotkeep 2>/dev/null
left=$(pgrep -f 'SANPK\.exe' 2>/dev/null | while read p; do lsof -p "$p" 2>/dev/null | grep -q 'prefix-fengye-shadow' && echo x; done | wc -l | tr -d ' ')
say "已關閉 ${n} 台；剩餘風夜遊戲：${left}"
pgrep -f 'SANGUO\.exe' >/dev/null && say "大廳 SANGUO 保留" || say "大廳未在跑"
pgrep -f 'launch_shadow_sticky.py' >/dev/null && say "協議會話保留（下次一鍵可直接進）" || say "協議會話不在（下次一鍵會重新登入）"
echo "{\"closed\": $n, \"left\": $left}"
