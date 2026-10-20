#!/bin/bash
# 風夜 probe 一鍵（headless 風夜版）
#   probe 進房 → 使用者開局 → cmd9 → sync → D8 摘席 → 被動旁聽
#   Hub 控制：hub_control.json（Hub 寫）→ hub_control_result.json（probe 寫）
#   D5 授權：hub_d5_auth.json（Hub 的 ProbeSender.arm 寫，600 秒有效）
# 前置：使用者已建房；probe 帳號/暱稱固定在 SHADOW_USER；主機為丁滿。
set -euo pipefail
LAB="$HOME/sgi-fengye-lab/shadow"
Z='Z:\Users\vk\sgi-fengye-lab\shadow'
W="$HOME/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine"
P="$HOME/sgi-fengye-lab/python32/python.exe"
PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow"
SHADOW_USER="${SHADOW_USER:-待秋至}"
TARGET="${1:-}"
LOG="$LAB/p34_one_click.jsonl"
HOLD="${HOLD:-7200}"
export WINEPREFIX="$PREFIX" WINEDEBUG=-all
export DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib"
export PYTHONIOENCODING=utf-8

if [ -z "$TARGET" ]; then
  echo "用法: one_click_probe.sh <target-host-ip>   (或先跑 p26_find_host.py 取得)"
  exit 2
fi
mkdir -p "$LAB"
echo "probe 風夜：$SHADOW_USER → $TARGET"
PROBE="Z:\\Users\\vk\\Documents\\Coding\\三国志internet\\research\\client\\protocol-lab\\p34_d8_probe.py"
"$W" "$P" "$PROBE" \
  --target "$TARGET" \
  --username "$SHADOW_USER" \
  --hold "$HOLD" \
  --log "$Z\\p34_one_click.jsonl" \
  --control-file "$Z\\hub_control.json" \
  --control-result "$Z\\hub_control_result.json" \
  --d5-authorization-file "$Z\\hub_d5_auth.json" \
  --d8-authorization-file "$Z\\p34_one_click_d8.json" \
  --observe-seconds "${OBSERVE:-3600}" \
  --execute
