# 代送閘門修復（0.2.34，2026-10-20）

## 1. 使用者回報

春季內政下的 6 筆建設（5 陷阱＋1 弓房，漁陽），過了兩個季度仍未送出；隊列顯示
「處理中 6、已完成 0」，第一筆「等內政回合執行」，其餘「已排隊」。

截圖上的加入時間 `5:23:21` 實為 `15:23:21`（欄位把 leading 1 切掉）。

## 2. 實測時間線（第一筆 d9598dd857，陷阱 73,21）

| 時間 | 事件 |
|---|---|
| 15:23:21 | submit；`phase_at_submit = 1`（風夜當時在春季內政） |
| 15:23:28 | Hub 依原設計「等本回合結束後借席」，狀態 `waiting_phase_exit` |
| 15:24:18 | 春季內政結束；切到燕（actor 5）的席位 slot 1 |
| 15:24:23 | `arming`（已不可安全撤回） |
| 15:24:24 | `waiting_phase`；agent 規則 `--require-phase 1` |
| 15:29:24 | 回執逾時 300 秒 → `unknown`；後 5 筆全部 `held`（前筆未確認） |

第一筆的 `p60_ui_7c60073212b9.flag` 留在 lab，沒有 `.bin` 回執 → agent 從未發射。

## 3. 為什麼等不到 phase 1

同一時間讀三個客戶端（roundprobe，唯讀）：

| | 丁滿（主機） | 風雲（玩家） | 待秋至（風夜） |
|---|---|---|---|
| phase_4d8 | 1（內政） | 1（內政） | **4（結算中）** |
| season_4d6 | 3 | 3 | **0（200 年春）** |
| sync roster | 2（丁滿＋風雲） | 1 | 1 |
| queue_84b4 | 0 | 0 | **5** |

- 風夜的視窗仍顯示「200年 春」；主機／風雲已進入後面的季節，畫面各剩 3／2 次指令。
- 主機的同步批次（control 5）最後送達 15:27:32，風夜的 DLL 有收到並排入 5 筆，
  但應用層沒有套用；它的 phase 停在結算 4。
- 風夜不在主機的同步名單（主機 2 人，風夜自己 1 人）。這與「開局前 D8 藏身、
  之後只靠廣播旁聽」的形態一致：第一個回合邊界之後，它的 app 回合狀態不再前進。

**根因兩層**：

1. 原面板在內政期下單時，刻意先等本回合結束，再切席位、武裝，目標是「下一個內政」；
   這會讓風夜在整個回合邊界都持有玩家的借席，正好踩在它最容易停擺的位置。
2. 風夜一旦停在結算，phase 永遠不是 1，agent 的 `--require-phase 1` 永遠不開；
   面板只會等 300 秒回執，然後以 `unknown` 堵住後續 5 筆。

## 4. 0.2.34 的修改

`command_service.py`：

1. **內政期內直接發送**：`_wait_for_domestic_phase()` 取代 `_wait_phase_exit()`。
   - `phase == 1` → 立即切席、武裝、發送、還席；不再等下一個內政。
   - `phase != 1` → **不切席**地等 phase 1（`phase_wait_timeout` 150→600 秒），可撤回。
2. **落後偵測（切席前）**：`reference_state()` 讀本機真實玩家（`prefix-sikarugir10`，
   退回 `prefix-dingman-local`）的 phase/season；`_staleness_error()` 在
   shadow season < reference season 且 roster 相同時直接 `error`，訊息例：
   「代送客戶端（風夜）停在 season 0（phase 4），玩家端已在 season 3（phase 1）」。
   等待中每 20 秒重比；不同 roster 不比，避免跨局誤判；無本機真實端時跳過。
3. **切席後複查**：切席需數秒；若期間離開 phase 1，立刻還席並 `error`（不武裝），
   不把借席帶進下一回合。
4. **還席家修正**：`_ghost_home_slot()` 先沿用 `slot_pending_restore` job 的 `slot_home`，
   不再把 slotkeep 的目標玩家 `--slot` 當成家。
5. **回執逾時說明**：`_wait_receipt()` 逾時時重讀 phase/season，寫入 `stall_note`；
   `command_presentation.progress_text()` 的 `unknown` 直接顯示，不再只有「結果待確認」。

`command_presentation.py`：等待文案改為「等內政階段（phase 1）…還沒送出」與
「已武裝；內政階段一到就會發送」，不再暗示同一個內政期會執行。

## 5. 驗證

- `python3.14 -m unittest discover -s tests` → **293/293**。
- 新增回歸：current-phase 直接發送、切席前落後拒絕、等待中真實端超前中止、
  不同 roster 不誤判、pending job 保留家、unknown 顯示 stall note。
- 真唯讀（本機三開，15:40 左右）：
  - shadow = `{'phase': 4, 'season': 0, 'roster': (16, 5, -1, ...)}`
  - reference = `{'phase': 1, 'season': 3, 'roster': (16, 5, -1, ...)}`
  - `_staleness_error` = 「代送客戶端（風夜）停在 season 0（phase 4），玩家端已在 season 3（phase 1）；請重啟風夜或改用玩家端代送」

## 6. 限制與下一步

- **本局風夜已停擺，且局中不能重新入座**（RefuseUser）；舊 `unknown` job 仍會擋同進程新單。
  這一局的面板代送不可用，需手動下單或改用風雲客戶端。
- 本輪**沒有實送任何遊戲指令**；「內政期內直接切席發送」需下一局實機 smoke 才算端到端成功。
  驗收點：submit 時 phase=1 → 數秒內 receipt → 遊戲出現新建物 → 自動還席（slotkeep 回到 home）。
- 風夜為什麼在第一個回合邊界停住（開局前 D8 vs 同步名單）仍需獨立實驗；面板現在的職責是
  **不把停擺誤當成等待**，並在切席前給出可讀的失敗原因。
- 遠端主機（本機沒有真實玩家 prefix）時，落後偵測會跳過；此時仍可代送，但沒有這層保護。
