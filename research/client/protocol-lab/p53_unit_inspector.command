#!/bin/bash
set -euo pipefail
# Open only the independent read-only inspector, initially DISARMED.
ssh -o BatchMode=yes -o ConnectTimeout=8 "${SGI_SHADOW_SSH:-vkquant@vkquant-com}" \
  'open -n "$HOME/sgi-protocol-lab-20260915/shadow/tools/P53UnitInspector.app"'
