#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
 echo "请先从 python.org 安装 macOS Python 3.12（含 Tk），然后重试。"; read -r; exit 1
fi
if ! python3 -c 'import tkinter; import sys; assert sys.version_info >= (3,10)' ; then
 echo "当前 Python 缺少 Tk 或版本过低。请安装含 Tk 的 macOS Python 3.12。"; read -r; exit 1
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'from PIL import ImageTk' >/dev/null 2>&1; then
 .venv/bin/python -m pip install -r requirements.txt
fi
mkdir -p logs
printf "请在游戏同一 CrossOver Bottle 中运行 bridge/Start-Bridge.bat。\n"
.venv/bin/python -B app/mac_main.py 2>&1 | tee logs/mac-last-run.log
