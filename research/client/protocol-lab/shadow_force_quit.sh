#!/bin/bash
# 風夜強制退出（強退）：停所有研究鏈輔助 + 停會話 + wineserver -k（影子前綴）。
# 用於客戶端卡死/半死時；正常收線請用 stop_shadow.sh。
set -u
cd "$(dirname "$0")"
source ./_env.sh 2>/dev/null || true
echo "[1/4] 停輔助鏈（keep/watcher/recorder）"
pkill -f "watch_peer.sh" 2>/dev/null || true
pkill -f "shadow_slotkeep" 2>/dev/null || true
pkill -f "shadow_slotwatch" 2>/dev/null || true
pkill -f "shadow_session_rec" 2>/dev/null || true
pkill -f "p33_host_watch" 2>/dev/null || true
pkill -f "rx_watch" 2>/dev/null || true
pkill -f "shadow_sampler" 2>/dev/null || true
pkill -f "shadow_auto_fire" 2>/dev/null || true
pkill -f "shadow_round_keeper" 2>/dev/null || true
sleep 1
echo "[2/4] 停會話（STOP + helper SIGTERM + wineserver -k）"
bash stop_shadow.sh 2>&1 | tail -3
sleep 2
echo "[3/4] 複查殘留"
LEFT=$(ps aux | grep -F "prefix-fengye-shadow" | grep -v grep | wc -l | tr -d " ")
echo "影子前綴殘留進程數: $LEFT"
if [ "$LEFT" != "0" ]; then
  ps aux | grep -F "prefix-fengye-shadow" | grep -v grep | awk "{print \$2, \$11, \$12}" | head -5
  WINESERVER="$HOME/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wineserver"
  if [ -x "$WINESERVER" ]; then "$WINESERVER" -k 2>/dev/null || true; sleep 2; fi
  LEFT=$(ps aux | grep -F "prefix-fengye-shadow" | grep -v grep | wc -l | tr -d " ")
  echo "二次清理後殘留: $LEFT"
fi
echo "[4/4] 完成"
date
