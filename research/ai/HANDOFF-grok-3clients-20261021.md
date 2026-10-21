# HANDOFF — 三客戶端一鍵內測（給 Grok 繼續修）

## 專案位置
- 實驗室腳本：`~/sgi-fengye-lab/shadow/`（一鍵：`one_click_test.sh`，子 log：`logs/one_click-<ts>-{dingman,fengyun,fengye}.log`）
- 風夜 Hub（Python/Tk）：`research/client/fengye-omni-hub/`（名稱已改 **化神指揮部**，0.2.88）
- 啟動器（Swift）：`scripts/wine-launcher/main.swift`（build：`scripts/wine-launcher/build.py`；產物 `~/Desktop/三国志 Wine.app`）
- 快速軍令（Python/Tk）：`research/client/SGI-Hub-CrossOver-M4-0.2/app/quick_control.py`

## 目前三個未解問題

### 1) 一鍵內測：風夜 helper 在 +2 秒退出，但遊戲其實會起來
證據 `logs/one_click-20261021-085744-fengye.log`：
```
{"ev":"hold_started","helper_pid":26702}
{"ev":"helper_gone_during_hold","code":1}   ← +2s 就死
{"ev":"session_closed"}
```
同一輪結束後 `pgrep SANPK` 卻有 `prefix-fengye-shadow` 的進程 → **client 有起來，是 helper 太早放棄**。
建議：helper 的「等遊戲視窗出現」逾時從 2 秒改成 60 秒；或 helper 退出不要讓整條鏈判定失敗。
（`one_click_test.sh` 的 6d 智能守衛已註解停用；`SKIP_MYFORCE` 預設 1。）

### 2) 啟動器：下架「歷史回放」「戰局檔案」
`scripts/wine-launcher/main.swift`
- 115–116 行（首頁兩塊磚）
- 343 行（工具頁那塊）
作法：**註解掉**（程式碼保留，日後可恢復），不要刪。改完 `python3 scripts/wine-launcher/build.py` 重建 .app 並重啟。

### 3) 啟動器：一鍵內測卡住不恢復
同一支 `main.swift`，約 307 行「一鍵內測執行中」的狀態機。
需求：**使用者手動關閉所有客戶端後，5 秒內恢復可再按**。
判定：`pgrep -f SANPK.exe` 為 0（或三個 prefix 都沒有 SANPK）→ 清掉 running 狀態並顯示「已中止（客戶端已關閉）」。

## 已做完（不要重做）
- 化神指揮部：開局綁定（玩家真名下拉）、切換速鍵、登入帳號可改、席位自動校正、
  狀態列說真話、未坐定不准按開始、網線心跳（130s 黃 / 260s 紅）、回合同步偵測、快速軍令不再自動開。
- `shadow_force.sh switch` 從 10–12 秒降到 1.6 秒。
- `patch_start_nulls.py` 支援 `--skip myforce-a,myforce-b`（智能守衛 `patch_myforce_guard.py` 已寫入流程，但目前 6d 停用中）。

## 紅線
- 不改遊戲 EXE、不覆蓋存檔、不動主機（陌生人）端。
- 收集器 `~/sgi-direct-connect`（direct_connect.py）與一鍵內測**不可同時跑**（搶同一個風夜客戶端）。
- 修改任何腳本前先備份到 `/tmp`，改完跑語法檢查（`bash -n` / `py_compile`）。

## 追加三項（2026-10-21 09:34 使用者要求）

### 4) 補丁顯示 16/18「缺 開局守衛」是假警報
化神指揮部狀態列讀到 `守衛 16/18·防崩 21/21·抑制 2/2·缺 開局守衛`。
真相：16/18 缺的兩個就是 **`myforce-a` / `myforce-b`**，因為 `one_click_test.sh` 6c 對風夜帶了
`--skip myforce-a,myforce-b`（`SKIP_MYFORCE` 預設 1）。
要求：計數時把「依設定跳過」的站算成已裝（`ok = patched + skipped`），或顯示成
「18/18（2 站依設定跳過）」，不要讓它顯示「還沒裝齊 / 還不能按開始」。

### 5) 進度條
化神指揮部狀態面板做一條一鍵進度條：讀 `~/sgi-fengye-lab/shadow/one_click_state.json`
（欄位 `step` / `status` / `detail` / `at`）與 `logs/one_click-<ts>.log` 的行，
把「啟動三鏈 → 等游戏选择 → 建房/進房 → 補丁 → 摘席 → 占席 → 完成」映射成 0–100%。
`status=ok` 且 `step=done` → 100%。

### 6) 速度優化（補丁與綁定）
- 補丁：`patch_start_nulls.py` 目前每站都 read→write→readback；可一次 VirtualAllocEx 後連續寫入，
  最後一次 flush + 統一回讀驗證（3 台 × 21 站可省掉大量 Wine 往返）。
- 綁定：`switch_ghost_seat` 已是 1.6 秒；剩下的延遲來自 `shadow_setforce.py` 的 wine 啟動（約 1 秒）。
  可把「設定席位」與「重啟 slotkeep」併成一次 wine 呼叫，或讓 slotkeep 自己輪詢 `setforce-now.json`
  變更，避免每次切席都重啟進程。
