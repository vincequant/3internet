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
# Prepare PlayBGM=0 only when SANPK is not running, then open lobby + observer.
exec "$PY" -B app/quiet_wait_launch.py
