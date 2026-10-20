# 下一窗口提示詞（2026-10-20 第三棒，接 0.2.30）

> 用法：整段貼給下一個窗口當第一則訊息。

---

你是《三國志Internet》研究專案（`/Users/vk/Documents/Coding/三国志internet`）的接手機位。

先讀這兩份（依序）：
1. `HANDOFF_20261020_地圖縮放與斷線.md`（環境、紅線、證據索引）
2. `research/client/fengye-omni-hub/AGENTS.md` 最下面 **0.2.30** 那條（本窗剛做完的事）

## 0. 狀態（0.2.30 已 commit：`816cfd0`）

**這窗把「一滾就下移」的真因找出來並修掉了**，但**還有一個尾巴沒收**（見第 2 節）。

已完成：
- **相機夾邊界改成游標錨點優先**（`native_window.py: map_clamp_axis`）。
  根因不是算式，是「底圖比畫布小時把水平相機釘死中央」→ 水平軸不吃游標錨點。
  實測第一格滾輪：游標底下橫向位移 **56~64 px → 0.05~0.19 px**；連滾兩格 0.00 px。
- 滾輪 40 ms 節流（觸控板一個手勢不會衝到上限）、新增拖曳平移、提示改「拖曳／WASD 平移」。
- 縮放後把相機中心夾到新倍率的合法值再存回去（不會有「舊的想去的中心」留在地圖外）。
- 測試 `python3.14 -m unittest discover -s tests` → **108/108**（新增 12 條回歸測試，
  舊版夾邊界下會失敗）。
- 面板已重啟（0.2.30 在跑），`/tmp/hub-map-debug.log` 會記錄畫布幾何。

**最重要的一條方法論（別再踩）**：
> Tk 的 `event_generate('<MouseWheel>')` 在 **withdraw() 的隱藏視窗**裡 **不會送進 binding**。
> 上一窗就是用隱藏視窗量測的，所以量到「沒有位移」——那是假象，事件根本沒進來。
> 要量必須用**已對映**的視窗（`root.geometry('+3200+2000')` 移到螢幕外也算對映）。

## 1. 已排除的可能（別重做）

- **不是算式錯**：`map_project` / `map_unproject` / 錨點數學都對，
  用真實 Tk 事件 + 「底圖像素反推畫布座標」量，端到端位移 < 0.2 px。
- **不是 Tk 畫布捲動**：log 裡 `battle canvas geom=` 顯示
  `scrollregion=() xview=(0,1) yview=(0,1) img_item coords=(220.0,-0.0)`，
  畫布邏輯狀態完全正確。
- **不是 0.2.30 造成的**：0.2.29 版重啟後也會出現（第 2 節的現象）。

## 2. 還沒收的尾巴（下一窗的第一件事）

**現象（0.2.30 面板實測，`docs/panel-20261020-mapfix-1x.png`）**：
戰場頁的 canvas 上，**整張內容（地形圖塊＋城池方塊＋名稱）被畫到畫布底部**，
畫布上面 90% 是空的深綠色（`MAP_FILL`），只有最下面一條 ~17~40 px 露出地圖最上面一排城
（昆侖／黑風寨／代縣／薊／漁陽／昌黎／襄平）——那正是 1x 全圖的最北緣。

矛盾點：
- log 顯示畫布邏輯完全正確（上面第 1 節）→ **不是 Tk 捲動、不是相機**。
- 但截圖就是錯的 → 要嘛是 **macOS Tk 9 的 canvas 圖層合成問題**，
  要嘛是 **視窗內容被 stale frame 疊加**（畫布背景是一層、圖塊是另一層）。
- 同一台機器上 `ImageTk.PhotoImage` 在 canvas 上**有時畫得出、有時畫不出**
  （本次用最小重現測出：同一份程式碼，一次 capture 有 21 萬個紅色像素、另一次 0 個）。
- `screencapture -l<windowid>` 對 Tk canvas 的 photo 層**可能抓不到**（最小重現時
  視窗用 `-R` 區域截圖反而抓得到）→ **截圖方法本身要標準化**。

**建議的收尾順序**：
1. 先確定是「畫面真的錯」還是「截圖抓不到」：
   在面板開一個 Tk canvas 放一張 PIL 圖 + 一個 `create_rectangle`，
   同時用 `screencapture -l` 和 `-R` 兩種方式各截一次，比對。
2. 若是真的錯：試 `canvas.update_idletasks()` / `canvas.tk.call('update')` /
   重新 `itemconfigure(image=...)` / 關掉 `takefocus` / 取消 `<Enter>` 的 `focus_set()`
   逐一排除。
3. 若只是截圖抓不到：用 `canvas.postscript()` 匯出成圖（不依賴螢幕合成）當驗收圖。

## 3. 使用者還沒確認的點

- **實滾一次**：現在相機錨點在數學上已經正確（實測 < 0.2 px），
  但請使用者實機滾一次確認「游標底下那一點有沒有留在原處」。
- 使用者正在線上測試（10:20~10:30 之間有連續 WASD 輸入的 log），
  改動後**記得 `pkill -f FengyeHub` 再重開**，否則使用者測的是舊行程。

## 4. 背景（不要重做）

- **建設去重**（0.2.29）：`_p60_occupied.py` ＋ `CommandService.occupied_cells()` /
  `busy_build_cells()`，`validate()` 會擋「該格已有物件／已在佇列／剛送出」。
  面板層攔阻；已疊在存檔裡的舊陷阱不會消失。
- 遊戲端 `0x4515a8` 的 4/5/6 分支建物件前**不查佔用**，所以只能面板層擋。
- 外部指令頁共用同一套相機／投影（`map_camera` / `map_project`），1x 置中 view 未變。
- **同盟頻道旁聽判定**（P0，未做）：見 `research/ai/p60-chat-interception-20261020.md`。
  決定性實驗：自測局丁滿×風雲結盟 → 一方在同盟頻道發一句 → 幽靈端（非同盟）看是否收到同型幀。
- **情報台「讓某人掉線」按鈕**（P1，未做）：工具 `research/client/protocol-lab/p63_drop_inject.py`
  （在目標自己的 prefix 內注入 ExitProcess → 主機 30–40 秒顯示「恢復連線中→無法重新連線→退出」）。
  **不要從 shell kill。** 破壞性操作逐次確認。
- 紅線：3v3 無電腦席、不能多第 7 勢力；進房必留一行；局中掉線需幽靈開局前已在房；
  不動存檔；破壞性動作先問。
- 採集流（recorder）停擺：面板會顯示「遊戲資料停下來了」，重跑 `arm_now.sh`。

## 5. 環境速查

| 項目 | 值 |
|---|---|
| 情報台原始碼 | `research/client/fengye-omni-hub/`（`run.py` → `native_window.py:FengyeWindow`） |
| 重啟面板 | `pkill -f FengyeHub; open "$HOME/Library/Application Support/SGI-Wine/風夜全知情報 Hub.app"` |
| 指定分頁/倍率 | `launchctl setenv FENGYE_START_TAB 戰場; launchctl setenv FENGYE_BATTLE_ZOOM 1.0` 再 `open`（`open --env` 不會傳環境變數） |
| 地圖除錯 | `/tmp/hub-map-debug.log`（帶時間戳，含 `battle canvas geom=` 畫布幾何） |
| 分頁記錄 | `/tmp/hub-tab-debug.log` |
| 截圖 | `swift /tmp/winid.swift 風夜情報台` 取 id → `screencapture -x -o -l<id> out.png`；視窗位置用 `/tmp/winrect.swift` |
| 本窗驗證工具 | `/tmp/tk_anchor_harness.py`（真實 Tk 事件 + 底圖像素反推）、`/tmp/tk_scroll_probe.py`（畫布捲動狀態） |
| 測試 | `cd research/client/fengye-omni-hub && /opt/homebrew/bin/python3.14 -m unittest discover -s tests`（**一定要 3.14**，3.13 沒 PIL） |
| lab | `~/sgi-fengye-lab/shadow`（`_env.sh` 提供 `$WINE` `$P32` `$Z`） |

## 6. 交付要求

改完：重啟面板 → 跑 `python3.14 -m unittest discover -s tests`（應 108/108 起）→ commit
→ 回覆「改了什麼、怎麼驗的、還有什麼風險」。
驗收圖優先用 `canvas.postscript()` 或可重現的截圖方式，並在回覆裡說明用的哪種。
