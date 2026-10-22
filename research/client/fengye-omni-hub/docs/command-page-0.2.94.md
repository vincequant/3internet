# 0.2.94：指令頁＝即時狀態／回合跟隨＋內嵌快速軍令（配色統一）

## 使用者要的（2026-10-21 19:5x）

> 「这三个功能感觉没甚么用，你应该是实时读出当前状态，并且看看有没有成功跟随回合
> （主要看120秒内有没有返回玩家信息，240秒作终结），把实验室的让对手掉线也转过来外部指令，
> 然后外部指令更名为指令。」
>
> 「颜色风格也进行一下统一 不要再用黄色风格。」

## 做了什麼

1. **分頁改名**：`外部指令` → **`指令`**（`native_window.py` 的 notebook 標題、`_open_quick_panel`
   的查找、`run.py` 的 `FENGYE_START_TAB` 說明、驗收腳本都同步）。
2. **拿掉三個手動鈕**：面板內嵌時不再顯示「重新连接／刷新状态／回合 +10 秒」（連 `Ctrl+Alt+F6`
   的加時熱鍵也不綁），改成頁面上的兩行自動狀態：
   - **即時狀態**（每秒刷新）：倒計時、階段（內政／軍事／結算）、已用指令 x/3、年份季節；
     面板還沒連上時直接顯示它的狀態字。
   - **回合跟隨**（新 `app/turn_follow.py`）：看風夜自己連線的累計收包數（`wire_health().received`）
     有沒有增加——也就是「玩家資訊有沒有回來」。後面再接三段：
     **收包時的回合 vs 現在**（例：`收包 200年春 → 現在 200年夏`，相同時寫「現在相同」）、
     **玩家端回合**（`sync_check()` 的結果：`與玩家端同步` 或 `玩家端已到 200年夏（風夜落後 1 季）`）、
     累計筆數。
     * `✓` 120 秒內有收到（顯示「N 秒前收到玩家資訊」＋年份季節）
     * `⚠` 超過 120 秒（顯示已靜默多久、240 秒判定）
     * `✗` 滿 240 秒 → **判定掉隊**（終結）；之後只要收到新資料就自動恢復，並標「先前中斷過，已恢復」。
     * 累計 0 筆不算「有資料」，維持「風夜還沒收到任何資料」；換 run（新連線／新局）重新計時。
3. **「讓對手掉線」搬家**：從「實驗室」頁搬到「指令」頁最下方（破壞性操作，維持 `askokcancel`
   二次確認、失敗不重試、風夜不在目標清單）。**「實驗室」分頁整個移除**——它唯一的內容就是
   這顆按鈕，留一行說明只是多一個空分頁；`_build_lab_page` 一併刪掉。
4. **配色統一**：面板改用呼叫端給的 `palette`（Hub 的淺藍白 `#f3f6fa`＋墨綠 `#286a72`＋
   `#e6eef2` 按鈕），米黃／金色只留給獨立視窗（`啟動快捷修改面板.command`）。`Panel` 的
   `palette` 可只覆寫單一顏色。
5. **兩個隱藏分頁徹底刪除**：「戰場」與「玩家與遊戲」不再只是 `hide()`——`battle_page`／
   `BattlePanel` 實例、`_battle_*` 地圖繪製／縮放／拖曳、`_build_local_controls`（本機進入／
   結束／強制結束、席位切換）、`fengyun_local` 匯入與每 10 秒的本機狀態輪詢全部移除。
   `fengye_battle_panel.py` 本身保留（`build_picker`／`fengye_force_views`／`fengye_capture_status`
   與測試仍在用）。
6. **聊天歷史加入遊戲時間＋勢力顏色**：
   - 時間：每條前面變成 `10-21 20:00:00 · 200年春`。聊天封包本身沒有年份季節，所以取
     「Hub 第一次看到這條訊息時」讀到的回合（`cmd_targets_data` 的 year/season），存在本機
     `data/chat-times.json`（重啟後仍在，最多留 600 條）；讀不到就寫「回合未記錄」，不補造。
   - 勢力：`丁滿（宋）`——勢力名從開局名單（`p34.snapshots.start.rows[*].faction`）按 sender id
     對回來。名字與內文都用該勢力的原作配色（`app/game_palette.json`，22 家）；
     晋／南蛮／西凉那種太亮的顏色會壓暗到白底可讀（`app/chat_force_colors.readable()`），
     查不到勢力就只顯示名字、用一般墨色。新模組 `app/chat_force_colors.py`。

## 檔案

| 位置 | 內容 |
| --- | --- |
| `app/turn_follow.py` | `TurnFollower`：`observe()`／`state()`／`describe()`，120／240 秒門檻，純邏輯 |
| `native_window.py` | 指令頁重建（狀態卡＋面板＋掉線盒）、`_tick_command_status`／`_render_command_status`／`_poll_command_wire`、`_build_drop_box`、`_panel_palette`、分頁改名 |
| `SGI-Hub-CrossOver-M4-0.2/app/quick_control.py` | `palette` 支援；內嵌時不建立那三個鈕（也不綁 F6） |
| `app/quick_command_embed.py` | `mount_quick_panel(..., palette=…)` 透傳 |

## 外觀

收合：[`command-page-0.2.94.png`](command-page-0.2.94.png)
展開「修改功能」＋捲軸：[`command-page-0.2.94-expanded.png`](command-page-0.2.94-expanded.png)
正式 `.app` 實機（0.2.94）：[`command-page-0.2.94-live.png`](command-page-0.2.94-live.png)
——分頁列＝進房與準備／指令／聊天歷史／勢力情報／勢力對比（**實驗室、戰場、玩家與遊戲都已移除**），
面板配色跟 Hub 一致，三個手動鈕不在畫面上；回合跟隨那一行是實機讀到的 `✓ 6 秒前收到玩家資訊｜…｜累計 2 筆`。

頁面由上到下：風夜席位（下拉＋切換＋狀態）→ 即時狀態／回合跟隨卡 → 快速軍令面板 →
讓對手掉線（紅框）。

聊天歷史（0.2.94）：[`chat-history-0.2.94.png`](chat-history-0.2.94.png)（示範資料，
用來看待機時間的排版；真實局只有實際收到的對話才會出現）。

## 驗收

```
python3.14 -m unittest tests.test_turn_follow     # 10/10
python3.14 -m unittest tests.test_quick_embed     # 18/18（2 項因實機 Hub 正持有面板鎖而 skip）
```

實機唯讀 harness（`native_window.FengyeWindow`＋replay、`SGI_QUICK_EMBED_AUTOCONNECT=0`）：

- 分頁清單＝`進房與準備／聊天與操作結果／指令／戰場／聊天歷史／實驗室／玩家與遊戲／勢力情報／勢力對比`；
- `manual_buttons_mapped = [false,false,false]`（三個手動鈕確實不在畫面上）；
- `Quick.TLabel` 背景＝`#f3f6fa`（Hub 配色，不是 `#ede3c5` 米黃）；
- 快捷鍵：F7 在「指令」頁命中一次、切走後不再命中；
- 掉線盒目標＝「丁滿（主機）」，按鈕存在；
- 回合跟隨文字（未連局）：`等待玩家資訊（風夜還沒收到任何資料）｜120 秒正常／240 秒判掉隊`；
  注入示範數據後：`✓ 剛剛收到玩家資訊｜120 秒正常／240 秒判掉隊｜收包 200年春（現在相同）｜
  玩家端已到 200年夏（風夜落後 1 季）｜累計 128 筆`。

## 沒做／限制

- 這一輪**沒有實局按鈕**、沒有送出任何掉線或遊戲指令；「掉線」只驗按鈕與參數（沿用 0.2.35 的
  `p63_drop_inject.py` 路徑）。
- `wire_health()` 讀的是風夜自己連線的 `state.json`；讀不到時回合跟隨顯示「讀不到風夜連線狀態」，
  不補造。
- 「玩家資訊」的語義＝風夜 session 的累計收包數變化；封包內容是否為回合資料不在此判定內。
- 全套件仍有一批**本輪之前就失敗**的項目（`command_service.py`／`backend/*`／`room_remote.py`
  被其他窗口改到一半：`test_command_session`、`test_command_dedupe`、`test_native` 的 backend 指紋、
  `test_room_line`、`test_rooms`）。本輪相關測試全過。
- Windows 原生 GUI 未實測；未改遊戲 EXE／存檔／實驗室鏈。
