#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")" || exit 1
mkdir -p logs
if [ ! -x .venv/bin/python ]; then
 echo "找不到 Hub 已配置的 Python 环境：$(pwd)/.venv/bin/python"
 echo "请保留此错误信息。按回车关闭。"; read -r; exit 1
fi
printf "正在启动三国志全知情报；采集桥会自动连接，无须另外打开。\n"
.venv/bin/python -B app/mac_main.py 2>&1 | tee logs/mac-last-run.log
result=${PIPESTATUS[0]}
if [ "$result" -ne 0 ]; then
 echo "启动失败（$result）。日志：$(pwd)/logs/mac-last-run.log"
 echo "请保留此窗口。按回车关闭。"; read -r
fi
exit "$result"
