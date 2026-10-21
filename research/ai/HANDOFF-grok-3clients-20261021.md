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
