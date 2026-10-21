# HANDOFF — 倒數比例拉桿（未做，接手第一件事）

## 需求（使用者原話）
「把倒數砍半這個移出來，做成拖動進度條，可以從 25%/50%/75%/100% 移動，
  25% 大概 30 秒，拖到 100% 維持 2 分鐘。」

## 定義
- 拉桿範圍 25%–100%，對應回合倒數長度：**25% = 30 秒、50% = 60 秒、75% = 90 秒、100% = 120 秒**
- 只影響風夜自己那台的回合倒數（原版機制：剩 1 秒時寫入截止時間）
- UI 即時顯示「= N 秒」

## 三個要改的檔案
1. `research/client/SGI-Hub-CrossOver-M4-0.2/app/quick_control.py`
   - 目前是 `啟用輔助：倒数砍半／指令×3／WASD视角`（約 91 行）
   - 加 `ttk.Scale`（25–100、步進 25）＋旁邊 `= N 秒` 標籤
   - 值放進 settings 事件（`round_percent`）
2. `.../bridge/quick_auto_timer.py`
   - 目前是「扣掉剩餘一半」：`delta = -int(remaining/2)`（約 110 行）
   - 改成：`目標 = 120000 * percent/100`；`delta = 目標 - remaining`
3. `.../app/quick_control_model.py`
   - `extension_remaining()` 目前允許任意整數（先前已改），確認 `extension_plan()` 也接受任意 delta

## 已知狀態（別重做）
- 切席 171ms（`shadow_force.sh` 只寫 `setforce-request.json`，slotkeep 0.1s 輪詢）
- 補丁整段讀寫、18 站自測通過
- 化神指揮部 0.2.88：守衛 18/18（2 站依設定跳過）、一鍵進度條、網線心跳 130/260s
- 一鍵內測三客戶端：目前可用（Grok 已修 helper 逾時）

## 紅線
不改遊戲 EXE、不覆蓋存檔；收集器 `~/sgi-direct-connect` 不可與一鍵同時跑。
