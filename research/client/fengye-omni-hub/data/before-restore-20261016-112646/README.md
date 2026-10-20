# 風夜 · 全知情報 Hub 0.1.4（桌面版）

從現有「三國志全知情報 Hub 1.1.336」複製的獨立 Tk 桌面程式；保留原版介面、原作素材與功能模組，新增風夜情報及操控台。原版 Hub 與網頁狀態頁繼續保留。

本程式不開瀏覽器、不啟動 HTTP 服務、不佔用 8765，也不啟動原版記憶體採集橋。視窗存在時每約五秒透過現有一次性 SSH 讀取探針檔案；沒有新增遠端常駐。

## 啟動

- Wine 導航 →「打開風夜全知情報 Hub」。原有 Hub 入口保留。
- Mac：執行 `啟動風夜Hub.command`，或 `python3 launch.py`。
- `python3 build_app.py` 安裝原生入口至使用者的 SGI-Wine 目錄。
- Windows：`启动风夜Hub.cmd`。需 Python、Tk 與 Pillow；套件沿用原版 `requirements.txt`，尚未完成原生 Windows 實機驗證。
- 未配置時，把 `config.example.json` 複製為 `data/config.json`，填入已授權來源；程式不詢問／複製密碼。
- `python3 run.py --replay /path/to/observation.json` 開啟原始觀測 JSON 的獨立回放視窗；使用暫存快取，不覆蓋在線快取，操控永遠禁用。

## 介面與證據範圍

「風夜情報」顯示訊框流、非空同步數據、聊天與控制事件；可篩選、搜尋、查看細節。右側顯示八席初始／開局快照、D8 回執及聊天。房間與線路 IP 區分來源，回放／離線／未就緒明確標示。

「風夜操控台」保留原有 chat／stop 兩種單次操作。GBK 可表示、1–120 字、至少兩秒間隔、僅在線探針可用；待回執期間禁用再次操作；失敗或不明結果不自動重發。收到寫入成功不顯示為已執行。退出前由使用者確認。

「房間與來源記錄」保留房間搜尋、成員、事件、線路目錄、會話與採集摘要，與開局八席快照分開。查房沿用既有中繼 SearchSession，不重新認證、不 OpenSession 入座。

**城池、武將、部隊與全景戰場的完整狀態尚未從風夜訊息解出。** 原版頁面及模組保留，但顯示資料尚未取得並停用原版輸入操作；不讀另一個 Hub 的 `/api/state`、不以本機記憶體資料冒充風夜情報、不將八席快照冒充完整世界資料。本次不擴展協議研究或自動開局。

桌面後端直接重用原有 `Sources` 與白名單展示函數；不啟動該模組裡的 HTTP 路由。原網頁服務的同源校驗與控制端點完全不變。展示不轉印原始後端物件；同步 hex 細節最多 240 字元。

## 驗證與打包

```sh
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy python3 -m unittest discover -s tests
python3 run.py --replay data/last-observation.json --verify-json data/native-verification.json --verify-exit
python3 build_dist.py
```

`UPSTREAM.json` 記錄複製時原版檔案 SHA256；`RELEASE.json` 記錄本副本版本。發行包以原版清單及明確新增檔案白名單打包，含 SHA256；不含 `data/`、SSH 目標、觀測快取、路徑設定、憑據、存檔、遊戲 EXE 或其他執行環境。本機私有資料只在安裝時從既有狀態 Hub 初始化，沒有加入清單。

原版介面使用本機 Python 3.14／Tk 9／Pillow 驗證。後端標準庫維持 Python 3.8 語法；桌面模組沿用原版執行環境，未宣稱已驗證 Python 3.8 的整套 GUI。
