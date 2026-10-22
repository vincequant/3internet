#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")" || exit 1
mkdir -p logs
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null; then
  PY=python3
else
  echo "找不到 Python。"; read -r; exit 1
fi
# No --watch: do not hide the game or change PlayBGM until the user enables refresh.
exec "$PY" -B app/room_watch.py
