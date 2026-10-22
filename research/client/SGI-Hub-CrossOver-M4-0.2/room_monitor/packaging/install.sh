#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
DEST="${SGI_ROOM_MONITOR_DEST:-$HOME/Library/Application Support/SGI-Room-Monitor/opt}"
DATA="${SGI_ROOM_MONITOR_HOME:-$HOME/Library/Application Support/SGI-Room-Monitor}"
SKILL="${SGI_ROOM_MONITOR_SKILL:-$HOME/.openclaw/workspace/skills/sgi-room-monitor}"
LAUNCH="$HOME/Library/LaunchAgents/ai.vkquant.sgi-room-monitor.plist"
mkdir -p "$DEST" "$DATA" "$HOME/bin" "$(dirname "$LAUNCH")"
rsync -a --delete --exclude credentials.json --exclude '*.token' --exclude live.json --exclude cache.json \
  "$ROOT/sgi_room_monitor/" "$DEST/sgi_room_monitor/"
rsync -a "$ROOT/grokbot_skill/" "$DEST/grokbot_skill/"
rsync -a "$ROOT/packaging/" "$DEST/packaging/"
rsync -a "$ROOT/tests/" "$DEST/tests/"
cp "$ROOT/VERSION" "$ROOT/config.example.json" "$DEST/"
HUB="$(CDPATH= cd -- "$ROOT/.." && pwd)"
printf '%s\n' "$HUB" > "$DEST/HUB_ROOT"
if [ ! -f "$DATA/config.json" ]; then
  cp "$ROOT/config.example.json" "$DATA/config.json"
fi
python3 - "$DATA/config.json" "$HUB" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]); hub=sys.argv[2]
data=json.loads(path.read_text(encoding='utf-8'))
data['hub_root']=data.get('hub_root') or hub
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
PY
umask 077
if [ ! -f "$DATA/control.token" ]; then
  python3 -c 'import secrets,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_hex(16)+"\n")' "$DATA/control.token"
fi
if [ ! -f "$DATA/credentials.json" ]; then
  printf '%s\n' '{ "username": "", "password": "" }' > "$DATA/credentials.json"
  chmod 600 "$DATA/credentials.json"
fi
mkdir -p "$SKILL"
cp "$ROOT/grokbot_skill/SKILL.md" "$SKILL/SKILL.md"
BIN="$HOME/bin/sgi-room-monitor"
sed -e "s|__DEST__|$DEST|g" -e "s|__DATA__|$DATA|g" "$ROOT/packaging/sgi-room-monitor.in" > "$BIN"
chmod 755 "$BIN"
sed -e "s|__DEST__|$DEST|g" -e "s|__DATA__|$DATA|g" -e "s|__BIN__|$BIN|g" \
  "$ROOT/packaging/ai.vkquant.sgi-room-monitor.plist" > "$LAUNCH"
echo "$DEST"
echo "$DATA"
echo "$SKILL"
echo "$BIN"
PYTHONPATH="$ROOT:${HUB}/bridge${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT/tests" -q
"$BIN" version
"$BIN" install-config >/dev/null
"$BIN" health >/dev/null || true
echo INSTALL_OK
