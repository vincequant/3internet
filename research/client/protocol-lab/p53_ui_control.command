#!/bin/bash
set -euo pipefail
# Administration Mac launcher; the remote helper only presents the menu.
# No install, arming, or inspector activation happens until a menu action.
ssh -t -o BatchMode=yes -o ConnectTimeout=8 "${SGI_SHADOW_SSH:-vkquant@vkquant-com}" \
  'cd "$HOME/sgi-protocol-lab-20260915/shadow" && source ./_env.sh && "$WINE" "$P32" tools/p53_ui_control.py'
