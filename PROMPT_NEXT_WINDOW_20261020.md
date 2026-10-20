# 下一窗口提示詞（直接貼給 MiniMax v3.1 flash）

你是《三國志Internet》研究專案（`/Users/vk/Documents/Coding/三国志internet`）的接手機位。
**先讀 `HANDOFF_20261020_地圖縮放與斷線.md`**（完整現狀、環境、紅線、證據索引都在裡面）。
本視窗的第一件事只有一個：**修好情報台「戰場」分頁的地圖縮放／平移**。

---

## P0（必做）戰場地圖滾輪縮放／WASD 平移

- 程式：`research/client/fengye-omni-hub/native_window.py`
  - 繪圖：`_battle_draw_map`、`_battle_view`、`_fit_map`
  - 互動：`_battle_set_zoom`、`_battle_wheel`、`_battle_pan`、`_battle_key`、`_on_tab_changed`
- 現況（0.2.28）：
  - 底圖＝遊戲世界地圖 `app/assets/SanInet.lbm`（525×350），世界座標 `WORLD=(101,202)`。
  - zoom ≤ 1.0001 → contain（整張等比置中）；zoom > 1 → 以畫布比例裁切、再等比 clamp。
  - 滾輪 factor 1.2（範圍 1–10）；WASD 每次平移可見範圍 10%。
  - **使用者回報：放大、縮小都會出問題**（地圖被拉走／變形／無法固定版面）。
- 要求：
  1. 先重現：用截圖比對 1x / 1.5x / 2.5x / 0.5 步進後的畫面，找出是「裁切比例」「座標投影」
     還是「事件重入」造成。
  2. 修到：1x 整張地圖等比置中；放大縮小**不變形**、以中心（或游標）縮放、地圖不位移；
     WASD 平移不越界；城池方塊與名稱跟隨地圖正確移動；切分頁回來仍是正確畫面；
     外部指令頁的地圖（`_cmd_draw_map` + `_fit_map`）也一致正常。
  3. 保留「重畫地圖」按鈕與 `/tmp/hub-map-debug.log` 除錯輸出（或改成更清楚的 log）。

## 環境與操作

```bash
# 面板重啟（App binary 內嵌 repo 的 run.py，改完存檔後重啟即生效）
pkill -f FengyeHub; open "$HOME/Library/Application Support/SGI-Wine/風夜全知情報 Hub.app"

# 直接開到指定分頁／縮放（除錯用）
FENGYE_START_TAB=戰場 FENGYE_BATTLE_ZOOM=2.5 \
  "$HOME/Library/Application Support/SGI-Wine/風夜全知情報 Hub.app/Contents/MacOS/FengyeHub" &

# 截圖（先取視窗 id）
swift /tmp/winlist_all.swift | grep 風夜情報台
screencapture -x -o -l<window-id> /tmp/battle.png

# 單元測試
cd research/client/fengye-omni-hub && python3 -m unittest discover -s tests
```

- 地圖繪圖參數會寫 `/tmp/hub-map-debug.log`（底圖載入、戰場 draw 的 w/h/photo/pos）。
- 目前沒有進行中的遊戲也能測地圖（地圖底圖與縮放不需要遊戲資料）。

## P1 同盟頻道旁聽（P0 修完再做）

- 未知：同盟聊天是「同盟廣播」還是「逐個 ChatTo」。路徑分析見
  `research/ai/p60-chat-interception-20261020.md`。
- 決定性實驗：自測局讓丁滿×風雲結盟 → 一方在同盟頻道發一句 → 幽靈端（DLL 成員、非同盟）
  看是否收到同型幀。收到＝可旁聽；收不到→再看中繼是否複製。

## 背景（不要重做）

- **D8 踢人**：開局前（host `+0x84A8=1`）立即生效；局中（`=3`）排隊到 `0x36e0` 回合邊界才落地，
  會造成「單向半連線」（名單還在、他說話主機聽不到、沒有斷線對話框）——**不自然，別當掉線用**。
  ABI：`0x4c80` 1 參、`0x4b60` 4 參（`(netobj,target,buf,len)`），**不要改**。
- **自然斷線（已完成）**：`research/client/protocol-lab/p63_drop_inject.py`（lab 也有副本）
  在**目標自己的 prefix** 內注入 ExitProcess；主機 30–40 秒顯示
  「恢復連線中→無法重新連線→退出」。**不要從 shell kill wine 客戶端**。
- **情報台外部指令（已完成）**：目標固定風夜、無乘數/數值欄、固定值
  （練兵 75／施捨 4／米交易 1000／建設 2000）、人事用下拉。
- **紅線**：3v3 沒有電腦席、多第 7 勢力一眼看穿；進房一定在主機應用層留一行，
  完全無痕不存在；局中掉線要求幽靈**開局前已在房**；不動使用者存檔；破壞性動作先問。
- **使用者偏好**：主要用「局中隨時掉線」，局前一般不用。

## 交付

- 改完請重啟面板並截圖（1x/2x）證明，跑 `python3 -m unittest discover -s tests`（應 50/50），
  把改動 commit 到 repo（訊息寫清楚），並在回覆裡列出「改了什麼、怎麼驗的、還有什麼風險」。
