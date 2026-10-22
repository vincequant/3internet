#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
SGI_BOTTLE="${SGI_BOTTLE:-SanguoInternet}"
SGI_CX_WINE="${SGI_CX_WINE:-/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine}"
if [ ! -x "$SGI_CX_WINE" ]; then
 echo "未找到CrossOver，请设置SGI_CX_WINE或从CrossOver的运行命令界面启动bridge/Start-Bridge.bat。"; read -r; exit 1
fi
if [ ! -d "$HOME/Library/Application Support/CrossOver/Bottles/$SGI_BOTTLE" ]; then
 echo "找不到Bottle：$SGI_BOTTLE"; read -r; exit 1
fi
mkdir -p logs
printf '目标Bottle：%s\n请先通过SANGUO.exe进入游戏地图。保持此窗口打开。\n' "$SGI_BOTTLE"
"$SGI_CX_WINE" --bottle "$SGI_BOTTLE" "$PWD/bridge/python/python.exe" -B -c 'import pathlib,runpy,sys; runpy.run_path(str(pathlib.Path(sys.executable).resolve().parent.parent / "windows_bridge.py"),run_name="__main__")' 2>&1 | tee logs/crossover-bridge.log
