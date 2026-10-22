# 0.2.93：快速軍令搬進「外部指令」頁（不再開獨立視窗）

> 後續 0.2.94 把分頁改名「指令」、拿掉三個手動鈕、配色統一並移入「讓對手掉線」；
> 本頁截圖已被 [0.2.94 紀錄](command-page-0.2.94.md) 取代（畫面不同，功能仍在）。

## 使用者要的

> 「你把快速军令的功能移入这个外部指令栏里，不用再独立打开快速军令。」

舊版外部指令頁只有「勢力／切換＋身份」和一個 **開啟快速軍令（獨立視窗）** 按鈕；按下之後
才在另一個視窗出現 560px 的「三国志 · 快捷修改面板 1.8.8」。本版把那塊面板**直接嵌進頁面**，
按鈕移除。

## 做了什麼

| 位置 | 內容 |
| --- | --- |
| `SGI-Hub-CrossOver-M4-0.2/app/quick_control.py` | `Panel(master, smoke=False, embedded=False, autoconnect=True)`：內嵌時不設標題／尺寸／置頂、不 destroy 別人的視窗、`fit_height` 停用、ttk 樣式改走 `Quick.*` 命名空間、快捷鍵只在所屬頁面顯示時作用、關閉只收輔助程式 |
| `fengye-omni-hub/app/quick_command_embed.py` | 用**檔案路徑**載入上面那份正本（Hub `app/` 內另有 1.8.7 舊副本）、`QuickPanelHost`（可捲動容器）、`mount_quick_panel()`、`SGI_QUICK_EMBED_AUTOCONNECT` 開關 |
| `fengye-omni-hub/native_window.py` | 外部指令頁＝風夜席位列 ＋ 內嵌面板；面板第一次切到本頁才建立；`dispose_quick_panel()` 供關閉時收線 |
| `fengye-omni-hub/run.py` | 關閉／「更新資料」重啟前先 `dispose_quick_panel()` |
| `fengye-omni-hub/app/quick_control_model.py` | 同步 1.8.8 的加時規則（任意非零 delta），保持與面板一致 |

## 行為

- **第一次切到「外部指令」頁**才建立面板；建立後跟獨立視窗一樣會自動連上本機對局
  （Wine 輔助程式），出現「遊戲倒計時」、按鈕依狀態開關。
- **切到別的分頁**：面板不銷毀，但 Ctrl+Alt+F6…F11 與 F5 **不在別頁生效**，避免在其他頁按鍵
  誤觸。
- **面板比頁面高**（展開「修改功能／外掛」時約 770px）→ 右側自動出現捲軸；收合時捲軸消失。
- **Hub 關閉／重新載入**：送 `quit` 給 Wine 輔助程式、關閉本次 log、釋放
  `~/.sgi-quick-control/panel.lock`。
- **與獨立視窗共存**：兩邊共用同一個單一實例鎖。若獨立視窗還開著，內嵌面板顯示
  「等待另一個快速軍令視窗關閉」並每 5 秒重試；關掉獨立視窗就自動接上——避免兩份面板同時
  對同一局送加時／訓練。
- 版面：面板置中、最寬 1040px（視窗變窄最低 680px），避免整排按鈕被拉成長條。

## 驗收

```
python3.14 -m unittest tests.test_quick_embed -v      # 16/16
```

實機（唯讀回放，`SGI_QUICK_EMBED_AUTOCONNECT=0`，不啟輔助程式、不送指令）走真正的
`native_window.FengyeWindow`：

- 切到「外部指令」→ 面板建立、`toplevels=0`（沒有多任何獨立視窗）；
- `panel_visible` 隨分頁切換 true/false；
- F6 在面板可見時命中一次、切到「進房與準備」後不再命中；
- 收合高度 594px（無捲軸）→ 展開 770px（出現捲軸）；
- 關閉面板不影響 Hub 主視窗。

截圖：[`quick-embed-0.2.93.png`](quick-embed-0.2.93.png)（收合）、
[`quick-embed-0.2.93-expanded.png`](quick-embed-0.2.93-expanded.png)（展開＋捲軸）。

正式 `.app`（0.2.93）實機畫面：[`quick-embed-live-0.2.93.png`](quick-embed-live-0.2.93.png)
——外部指令頁就是風夜席位＋內嵌面板，面板已自行連上（當時遊戲還在大廳，故顯示
「等待当前对局，自动重连中…」），沒有第二個視窗。

## 沒做／限制

- 這一輪**沒有**在實局按下任何面板按鈕，也沒有啟動輔助程式去讀遊戲；按鈕是否真的下達，
  沿用面板原本已驗過的流程（與獨立視窗同一份程式、同一支 Wine 輔助程式）。
- 面板自動連線只依 `http://127.0.0.1:8769/api/state` 與 SGI-Hub 的 bridge；Hub 自己不需要
  新服務。
- 全套件 341 項中仍有 24 項失敗，全部落在其他窗口改到一半的 `command_service.py`／
  `backend/*`／`room_remote.py`（`test_command_session`、`test_command_dedupe`、
  `test_native` 的 backend 指紋、`test_room_line`、`test_rooms`），與本版無關；
  `tests.test_quick_embed` 與 `test_map_events`、`test_native` 其餘項目皆過。
- Windows 原生 GUI 未實測；未改遊戲 EXE／存檔／實驗室鏈。
