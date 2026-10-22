#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
HUB="${SGI_HUB_ROOT:-$(CDPATH= cd -- "$ROOT/.." && pwd)}"
SKILL="${SGI_WAR_SKILL:-$HOME/.openclaw/workspace/skills/sgi-war}"
BIN="${SGI_WAR_BIN:-$HOME/bin/sgi-war-query}"
mkdir -p "$SKILL" "$(dirname "$BIN")"
cp "$ROOT/grokbot_skill/SKILL.md" "$SKILL/SKILL.md"
sed -e "s|__HUB__|$HUB|g" "$ROOT/packaging/sgi-war-query.in" > "$BIN"
chmod 755 "$BIN"
echo "$HUB"
echo "$SKILL"
echo "$BIN"
"$BIN" --demo summary >/dev/null
echo INSTALL_OK
