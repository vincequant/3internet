#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
DATA="${SGI_ROOM_MONITOR_HOME:-$HOME/Library/Application Support/SGI-Room-Monitor}"
cp "$DATA/config.json" "$DATA/config.json.bak" 2>/dev/null || true
cp "$DATA/dedup.json" "$DATA/dedup.json.bak" 2>/dev/null || true
sh "$ROOT/packaging/install.sh"
echo UPGRADED
echo "config preserved at $DATA/config.json"
