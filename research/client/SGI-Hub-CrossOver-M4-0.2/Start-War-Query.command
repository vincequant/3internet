#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null; then
  PY=python3
else
  echo "找不到 Python。"; read -r; exit 1
fi
export PYTHONPATH="$PWD/bridge${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -B bridge/sgi_war_cli.py "$@"
