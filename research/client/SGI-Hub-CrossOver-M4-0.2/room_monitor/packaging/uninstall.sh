#!/bin/sh
set -eu
LABEL=ai.vkquant.sgi-room-monitor
DEST="${SGI_ROOM_MONITOR_DEST:-$HOME/Library/Application Support/SGI-Room-Monitor/opt}"
SKILL="$HOME/.openclaw/workspace/skills/sgi-room-monitor"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" "$HOME/bin/sgi-room-monitor"
rm -rf "$DEST" "$SKILL"
echo "本机配置与凭据保留在 \$HOME/Library/Application Support/SGI-Room-Monitor"
echo UNINSTALLED
