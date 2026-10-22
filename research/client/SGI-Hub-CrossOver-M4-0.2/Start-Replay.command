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
exec "$PY" -B app/panorama_replay.py "$@"
