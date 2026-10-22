#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
 echo "请先运行 Start-Mac.command 完成依赖安装。"; read -r; exit 1
fi
.venv/bin/python -m pip install 'pyinstaller>=6,<7'
.venv/bin/python -m PyInstaller --noconfirm --windowed --onedir --name SGI-Hub --paths app --collect-all PIL --add-data "app/assets:assets" --add-data "app/card_catalog.json:." --add-data "app/game_palette.json:." --add-data "app/map.json:." app/mac_main.py
echo "已生成 dist/SGI-Hub.app（未签名，本机架构）。CrossOver 采集桥仍需单独启动。"
read -r
