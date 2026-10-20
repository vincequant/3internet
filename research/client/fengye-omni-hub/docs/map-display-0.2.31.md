# 0.2.31 地圖下沉修復（2026-10-20）

戰場與外部指令頁沿用全知情報全景地圖的 `SanInet.mbm` 地形來源。
這次保留 0.2.30 的相機數學，修正實際畫布被捲走的事件路徑。

## 根因與反證

已對映完整視窗中實測：圖塊 item 的座標仍是 `(220,0)`，`yview()` 仍為 `(0,1)`，
但 `canvasy(0)` 已是 **-396**。這會把地形、城池與文字全部往下畫。
前次根據 yview 排除畫布捲動的結論不成立。

繼承的全景地圖即使隱藏，仍安裝 Canvas 類別捲動處理。
戰場舊版只接 `<MouseWheel>`，Tk 9 的 `<TouchpadScroll>` 會走
`map_navigation._class_touch → _fallback_scroll → canvas.yview_scroll`。
每個事件實測下移 **36px**；當時沒設定 scrollregion，捲動不反映在 yview 比例中。

## 修正

- 戰場使用全景地圖同一套 `bind_pointer_wheel`，處理一般滾輪、Tk 9 packed
  觸控板事件、修飾鍵和 Linux Button 4/5。事件在縮放後被消化。
- 外部指令頁的固定全圖消化捲動事件，仍可點城池。
- 兩張畫布在尺寸變更時設定與內框等大的 scrollregion；考慮 border/highlight
  後，`canvasx(0)` 和 `canvasy(0)` 均固定為 0。平移只改相機。
- `/tmp/hub-map-debug.log` 現在記錄實際 origin，不能只用 xview/yview 驗收。

## 驗證與限制

```sh
cd research/client/fengye-omni-hub
/opt/homebrew/bin/python3.14 -m unittest discover -s tests
```

**115/115 通過**。新增 7 項測試使用已對映、移到螢幕外的視窗，安裝繼承全景地圖的
共用類別 binding，再發送真實 Tk 事件。0.2.30 下其中 6 項失敗；新版確認原點不動、
觸控板改變倍率、游標錨點、橫向／反向／細小手勢、普通滾輪與 Linux 按鈕、
拖曳、復原及切頁。測試遮蔽實體桌面游標，使用合成事件自身的 root 座標，
避免使用者同時操作滑鼠使測試變動。

正式 .app 已重建／重啟 **0.2.31**，使用者以原本出問題的實體輸入測試後確認：
**「已正常，地圖不再下沉」**。本次未對遊戲送指令、重啟遊戲或動存檔。

驗收圖使用已對映完整 Hub 的只讀驗收視窗：同時保存原生
`screencapture -l<windowid>` 截圖與 `canvas.postscript()` 匯出；PostScript 再由
Ghostscript 轉 PNG，不依賴螢幕 photo 圖層合成。截圖時只讀採集回報「沒有可讀的
客戶端」，所以圖中只有底圖，沒有補造城池／部隊；標記隨圖移動則由前述已對映
事件測試中的測試城池覆蓋。驗收視窗使用獨立回放快取；沒有操作主視窗的遊戲控制。
Ghostscript 未配置中文字型，PostScript 轉圖中的中文提示不完整，中文顯示以
原生視窗截圖為準。

- [完整視窗截圖](panel-20261020-mapfix-0.2.31-window.png)
- [Canvas PostScript 轉 PNG](panel-20261020-mapfix-0.2.31-canvas.png)

Windows 共用 Python 路徑維持相容，新增 TouchpadScroll binding 由既有 helper
在舊版 Tk 不支援時略過；Windows 原生 GUI 尚未實測。發行包以白名單打包，
335 檔逐檔 SHA256、必要檔案與變更路徑的 Python 3.8 語法核對通過。
白名單也補入既有 `command_service.py`（先前未入包）與地圖／去重回歸測試，
避免發行包漏掉原生視窗的既有必要匯入。
解壓發行包後執行 115 項測試：114 通過，1 項因獨立包沒有相鄰的
`fengye-status-hub` 原始碼，按既有規則略過來源逐位元組比對；原倉庫的同項比對通過。
