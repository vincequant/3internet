# 下一窗口提示詞（2026-10-20 第二棒，接 0.2.29）

> 用法：整段貼給下一個窗口當第一則訊息。

---

你是《三國志Internet》研究專案（`/Users/vk/Documents/Coding/三国志internet`）的接手機位。

先讀這兩份（依序）：
1. `HANDOFF_20261020_地圖縮放與斷線.md`（環境、紅線、證據索引）
2. `research/client/fengye-omni-hub/AGENTS.md` 最下面 **0.2.29** 那條（本窗剛做完的事）

## 0. 現在狀態（0.2.29 已 commit：`26a8fc2`）

- **戰場地圖**：底圖＝全知情報全景大地圖 `app/assets/SanInet.mbm`（9744×4872、48×24 交錯菱格），
  走 `app/tactical_terrain.py` 解碼。相機單一路徑 `scale = contain × zoom`，1x 整張置中、
  滾輪以**游標**為軸縮放、WASD 平移 10% 可見範圍並夾邊界、名稱重疊自動跳過、切分頁回來正確。
  外部指令頁共用同一套相機／投影。
- **建設去重**：`_p60_occupied.py` ＋ `CommandService.occupied_cells()` / `busy_build_cells()`，
  同一格已有物件／已在佇列／剛送出都會被 `validate()` 擋下。
- 測試 `python3.14 -m unittest discover -s tests` → **96/96**（注意：一定要用
  `/opt/homebrew/bin/python3.14`，3.13 沒有 PIL，地圖測試會 skip）。

## 1. 第一件事：跟使用者確認兩個「回報過但沒完全驗死」的點

**(a) 滾輪「一滾就下移」**
本窗用 in-process harness（真實 `FengyeWindow` + 合成 `<MouseWheel>`）量過：相機中心固定、
固定世界格在畫布上的位移 < 3 px，**無法重現**。已改成「以游標為軸縮放」來消除體感漂移。
請使用者實測一次：滾輪放大時，游標底下那一點是否留在原處？
若還會跑掉，請他貼 `/tmp/hub-map-debug.log` 最後 20 行（每行帶時間戳，含 canvas/zoom/scale/cam/anchor）。

**(b) 外部指令頁「地圖全黑」**
當時那台是舊進程。現在繪圖若拋例外會寫 traceback 進 `/tmp/hub-map-debug.log`，並在畫布上顯示
「地圖繪製失敗：XxxError」。若再看到黑畫布，直接看 log 尾巴就有答案。

## 2. P0（若上面都 OK，就做這個）：同盟頻道旁聽判定

未知：同盟聊天是「同盟廣播」還是「逐個 ChatTo」，見 `research/ai/p60-chat-interception-20261020.md`。

決定性實驗：自測局 丁滿×風雲 結盟 → 一方在同盟頻道發一句 → 幽靈端（DLL 成員、非同盟）
看是否收到同型幀。收到＝可旁聽；收不到 → 再看中繼是否複製（路徑 C）。

## 3. P1：情報台「讓某人掉線」按鈕

使用者主要用途就是**局中隨時掉線**。
- 工具已存在：`research/client/protocol-lab/p63_drop_inject.py`（在目標自己的 prefix 內注入
  ExitProcess → 主機 30–40 秒顯示「恢復連線中→無法重新連線→退出」）。**不要從 shell kill。**
- 要做：目標玩家下拉＋二次確認＋提示「會立刻斷線、約 30–40 秒主機顯示退出」。
- 破壞性操作逐次確認。

## 4. 背景（不要重做）

- D8 踢人：開局前立即（host `+0x84A8=1`）；局中（=3）排隊到 `0x36e0` 回合邊界才落地，
  會造成單向半連線——**不自然，別當掉線用**。
- ABI：`0x4c80` 1 參、`0x4b60` 4 參 `(netobj,target,buf,len)`，不要改。
- 紅線：3v3 無電腦席、不能多第 7 勢力；進房必留一行；局中掉線需幽靈開局前已在房；
  不動存檔；破壞性動作先問。
- 採集流（recorder）停擺：面板會顯示「遊戲資料停下來了」，重跑 `arm_now.sh` 或只重啟 recorder。

## 5. 環境速查

| 項目 | 值 |
|---|---|
| 情報台原始碼 | `research/client/fengye-omni-hub/`（`run.py` → `native_window.py:FengyeWindow`） |
| 重啟面板 | `pkill -f FengyeHub; open "$HOME/Library/Application Support/SGI-Wine/風夜全知情報 Hub.app"` |
| 地圖除錯 | `/tmp/hub-map-debug.log`（帶時間戳） |
| 開到指定分頁/倍率 | 直接跑 `.../MacOS/FengyeHub` 並帶 `FENGYE_START_TAB=戰場 FENGYE_BATTLE_ZOOM=2.5`（**`open --env` 不會傳環境變數**，要直接跑 binary；但用 bash 背景跑會被回收，建議寫 harness 或前景跑） |
| 截圖 | `swift /tmp/winid.swift 風夜情報台` 取 id → `screencapture -x -o -l<id> out.png` |
| lab | `~/sgi-fengye-lab/shadow`（`_env.sh` 提供 `$WINE` `$P32` `$Z`） |
| 掉線工具 | `WINEPREFIX=<目標 prefix> wine py32 tools/p63_drop_inject.py --target-name SANPK.exe [--plan]` |

## 6. 交付要求

改完：重啟面板並截圖（1x/2x）→ 跑 `python3.14 -m unittest discover -s tests`（應 96/96 起）
→ commit 到 repo → 回覆「改了什麼、怎麼驗的、還有什麼風險」。
