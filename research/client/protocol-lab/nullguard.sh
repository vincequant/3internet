#!/bin/bash
# Apply the runtime nullguard to the shadow SANPK (memory only; file stays original).
set -u
source "$(dirname "$0")/_env.sh"
"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode nullguard --target-name SANPK.exe
