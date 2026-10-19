#!/bin/bash
# 常駐回合驅動（2026-10-18）：重新注入「回合代理（無上限）」並視需要點火。
# 用途：追平/續跟；receipt 存在時先清（一次性紀律由本腳本明示清除）。
# 用法：bash inject_rounds_resident.sh            # 注入(max=2147483647，可用 MAX_ROUNDS 覆蓋) + 立即點火
#       bash inject_rounds_resident.sh --dormant  # 只注入不點火（之後 bash fire_round.sh）
# 注意：同進程已有代理在跟隨中時勿重複注入（避免雙驅動）。
set -u
cd "$(dirname "$0")"
source ./_env.sh
# ⚠ 2026-10-18 15:16 空轉事件：無上限（2147483647）暫停使用；預設回退 200（有界＋keeper 續跟）。
MAX="${MAX_ROUNDS:-200}"
rm -f shadow_round_c.flag shadow_round_c_receipt.bin
"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode rounds --rounds-variant b --target-name SANPK.exe \
    --agent-bin "$Z\\tools\\agent_rounds_c.bin" --bridge "$Z\\bridge" \
    --flag "$Z\\shadow_round_c.flag" --receipt "$Z\\shadow_round_c_receipt.bin" \
    --state "$Z\\inject-state-rounds-c.json" --max-rounds "$MAX" ${FORCE:-} | tail -4
if [ "${1:-}" != "--dormant" ]; then
  bash fire_round.sh
fi
