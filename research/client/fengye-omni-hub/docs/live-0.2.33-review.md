0.2.33 只讀審查（2026-10-20）

未改實作、未操作遊戲、未重啟或啟動來源。命名衝突、採集狀態與持續刷新為交叉審查；本代理曾實作 battle/force views，其部分屬作者復查，不冒充獨立審查。建設遮罩由其他執行者驗收，本次未重做。

發現一項 P2：`command_panel.py:356` 先執行 `render_jobs()`，再決定背景讀取。若同一筆當局記錄持續導致呈現例外，250ms tick 雖會重排，卻每次都在 `refresh()` 前拋出，因此畫面寫「自動重試」，指令頁實際不再讀新資料。純 Mock 注入已重現：`refresh_calls=0`、`tick_rescheduled=1`。具體可達輸入是時間戳 `created=1e30`：歷史載入只驗證有限數，`datetime.fromtimestamp()` 仍會 OverflowError。建議將讀取排程與時間線呈現錯誤隔離，並對不可表示的日期顯示未知／略過該列。這不會重送指令，戰場獨立讀取器亦未因此停下。

其餘核查：

- 命名隔離正確。實際同一 Python 程序載入 `fengye_command_effects.py` 與 `bridge/command_effects.py` 為不同模組；CommandService 的身分／效果入口均改用唯一名稱，發行白名單包含新檔。
- CaptureStatus 只計已觀測的不同快照；重複幀不增、同局舊時間不回退、換局重設、過期／失敗顯示重試，未宣稱寫入回放檔。頂部與 force views 共用已驗來源的 shadow 快照，未新增玩家來源。
- 命令讀取錯誤會入本機輪轉日誌，顯示友善狀態；正常讀取失敗仍持續排程。BattlePanel 對讀取／繪製例外保留時間與快照並再次讀取。
- 原勢力頁只重掛既有 widgets；active 頁面才執行原純 renderer。切頁 lift/lower 的原生 topmost 回歸已證明真的可見，離開不遮擋其他頁。原 fetch/tick 仍停用，沒有 source poll 或遊戲輸入入口。
- shadow prefix、readonly 與完整 entities 經 `prepare_payload` 核對；顯示衍生用 deepcopy，原始快照不改。未捕獲的指令不補造，內政區保留來源提示。

除了上述可恢復性缺口，本次未發現新的來源越界或重送路徑。未執行完整套件或 Windows GUI；沿用主代理正在進行的最終整合驗證。

結案補核：主代理已把背景讀取排程移至獨立 finally，呈現錯誤不再阻止新讀取；不可表示的加入時間顯示「時間未知」，事件日期亦處理 OverflowError／OSError。本代理只讀核對修正，並單獨執行 `persistent_timeline_error_does_not_starve_background_reads` 與 `unrepresentable_local_job_dates_are_unknown_and_do_not_break_queue`，**2/2 通過（2.69 秒）**。上述 P2 已結案，無本次審查尚未處理的問題。未重跑完整套件。
