#!/bin/bash
# Enable the host-invisible replay mode: NOP the two Koeinm member uploads
# (control1/control2) so the round driver D runs locally only. Runtime patches
# in the shadow process; revert with: bash suppress.sh --revert
set -u
source "$(dirname "$0")/_env.sh"
"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode suppress --target-name SANPK.exe "$@"
