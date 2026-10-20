# 情報台 0.2.35：版面、預計時間、實驗室掉線、去霧（2026-10-20）

## 1. 版面放大（使用者：全景地圖空間太少）

- `app/display_layout.py`：預設上限 1280×900 → **1400×1000**（1710×1107 螢幕實得
  1400×967；畫面截圖含標題列 1400×995）。
- `build_picker.EmbeddedConstructionMap`：地圖請求高度 320 → **380**。
- `command_panel`：隊列列高 3→2、詳情 2→1 行、周邊 padding 收窄；「勢力／立即讀取」與
  自動讀取狀態同列（狀態靠右）；建設提示移入地圖頁腳（原本佔一整行）。
- 截圖：`docs/command-page-0.2.35.png`（外部指令頁；剛啟動時勢力欄還在讀取）。

## 2. 預計執行遊戲時間（新欄位）

`CommandService.eta_text(phase, year, season)`：

| 目前 phase | 預計文字 |
|---|---|
| 1（內政） | `YYYY年X內政階段（現在）`（0.2.34 起在本次內政直接發送） |
| 0（回合開始） | `YYYY年X內政階段結束後`（本季） |
| 2–5（軍事／結算） | 下一季 `YYYY年X內政階段結束後`（冬→次年春） |

- 年份／季節取**真實玩家端**（`reference_state`，`f_4d0`/`f_4d6`），不是可能落後的風夜；
  外部指令頁每 60 秒在背景快取一次。
- 隊列新增「預計執行（遊戲時間）」欄（`job.eta_text`），詳情頁同步顯示。
- 這是估計，不是保證；若風夜落後，0.2.34 的落後偵測會在切席前直接報錯。
- 既有舊 job 沒有 `eta_text`，欄位顯示「—」；新 job 才有。

## 3. 實驗室：讓對手掉線

- 新可見子分頁「實驗室」（`native_window._build_lab_page`）。
- 目標：丁滿（主機，`prefix-dingman-local`）／風雲（`prefix-sikarugir10`）；風夜不可選。
- 按鈕「讓對手掉線」→ `CommandService.drop_client(prefix)` → lab
  `tools/p63_drop_inject.py`（一發 ExitProcess，約 30–40 秒主機顯示退出）。
- **每次 askokcancel 二次確認**、失敗不重試；「檢查本機客戶端」只讀 pid。
- 本輪**未實按**（破壞性）；只驗按鈕存在、服務參數、風夜被拒。
- 截圖：`docs/lab-drop-0.2.35.png`。

## 4. 風夜全域去霧（本局補裝）

本局 `one_click_test` 沒有跑 p52 godview（`shadow_status.fog_original=true`、無
`shadow_godview` 安裝），所以風夜畫面仍有灰霧。已對當前 shadow（pid 1456）以 p52 UI
交易安裝：

- `map-tiles`（tile-color renderer 的可見謂詞）
- `map-unit-sight`
- `map-unit-detail`、`map-city-detail`、`map-city-skin`、`map-site-detail`、`map-marker-detail`

狀態檔 `ui-state-godview.json`，全部 `enabled`；`shadow_status` 現回
`fog_original=false`、`godview.installed=true`。這是**執行期 lab 補丁**，不進發行包；
客戶端重開後要重裝（`arm_now.sh` 的 `GODVIEW=1` 流程包含 22 個元素）。

注意：截圖時待秋至視窗是 `onscreen=false`（最小化／被移到畫面外），所以用
`screencapture -l` 抓到黑畫面；把視窗還原即可看到去霧結果。程序仍存活，狀態讀數正常。

## 5. 聊天歷史與同盟頻道

- 目前「聊天歷史」顯示的是風夜連線收到的 **type-3 本地投遞**與公開聊天；發送者名稱由
  席位名單比對。頁首已加註「同盟／私聊是否可旁聽尚未驗證（P60）」。
- P60 靜態結論：私聊是定向 `ChatTo`，幽靈不是收件人 → 架構上拿不到；同盟頻道是
  「同盟廣播」還是逐個定向**尚未實測**。
- 要判定同盟：自測局讓丁滿×風雲結盟 → 一方發一句同盟訊息 → 在風夜 session 的
  `packets.jsonl`/pcap 看有沒有同型幀；收到才代表可旁聽（還需處理 App 層 sender 不在
  名單就丟的問題）。目前**不宣稱**已破同盟聊天。

## 6. 驗證

- `python3.14 -m unittest discover -s tests` → **296/296**。
- 新增測試：`eta_text` 格式（現在／下一季／跨年）、submit 保留 payload ETA、
  drop 只允許本機玩家且使用 p63、風夜被拒。
- 實機：.app 重啟 0.2.35，外部指令頁與實驗室頁截圖如上；未實送遊戲指令、未按掉線鈕。
- Windows 原生 GUI 未實測。
