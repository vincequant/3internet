#!/bin/sh
set -eu
BIN="${HOME}/bin/sgi-room-monitor"
LABEL=ai.vkquant.sgi-room-monitor
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
else
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LABEL.plist" 2>/dev/null || true
  launchctl enable "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || "$BIN" start
fi
echo STARTED
