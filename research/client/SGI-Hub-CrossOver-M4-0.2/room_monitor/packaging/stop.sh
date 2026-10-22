#!/bin/sh
set -eu
LABEL=ai.vkquant.sgi-room-monitor
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
"$HOME/bin/sgi-room-monitor" stop || true
echo STOPPED
