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
# Room watch + panorama live here, not in Hub.
if [ -d "$HOME/Library/Application Support/SGI-Wine/三国志 Wine.app" ]; then
  exec open "$HOME/Library/Application Support/SGI-Wine/三国志 Wine.app" --args --nav
fi
exec "$PY" -B app/wine_nav.py
