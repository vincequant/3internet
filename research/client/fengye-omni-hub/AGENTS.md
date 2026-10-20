
- **長局穩定第二次失敗＋修復（2026-10-17 14:07）**：內測多人局（13:33 開局）中風夜於 14:07:05 `viewer_heartbeat_expired` 自退（最後心跳 14:05:35；此前 14:06:58 遊戲方有成員離場事件＋ctrl8）。判定：觀眾心跳 90s 窗口太緊（長局中任何 SSH/輪詢打嗝即誤殺）。**已修**：`room_probe` 心跳寬限 90→300 秒（下次登入自動部署）；真斷開仍正常收尾。**局中接回=不可行**（風夜退出後無法中途接回，且本局 8 席已滿無空位）→ 續接研究須**結束本局→重新建房→重新進入**。

- **0.2.13（2026-10-17 15:5x，用戶回報「看不到當前局勢」）**：根因＝風夜四個分頁藏在「風夜情報／操控台」外層分頁內的子分頁列、預設還停在「操控台」，旁邊整排原版「玩家視角」空頁（永久關閉）造成誤導。修正：風夜四分頁提升為主分頁列（**本局局勢**／風夜操控台／房間與來源記錄／風夜指令解讀），**預設開在「本局局勢」**；原版 15 個玩家視角分頁全部 `hide()` 收起；統計行新增「已見動作 N 條、對話 K 條」；run.py 驗證器同步改。30/30 測試、replay 驗證（render_error=null、selected=本局局勢、original_pages 全 hidden、席位 8 行、解碼 37 條）；dist `fengye-omni-hub-0.2.13.zip`；Hub 已重啟（PID 32171）。

- **0.2.14（2026-10-17 16:0x，用戶問「沒以前豐富/清晰」＋「無法讀玩家內存值?」）**：①答覆：舊玩家 hub 的豐富＝讀玩家端內存重建（全地圖/部隊/武將/資源）；風夜 hub＝網路可見（席位/君主+指令+對話+節拍）為天花板；內存值在真實局結構性不可得（玩家機器不歸我們），內測技術上可得但屬用戶 10/17「永久排除玩家記憶體來源」定案 → 已呈 A/B/C 選項待用戶裁決（不主動改）。②清晰化落地：指令解讀頁發送者改「名字（勢力）」、CSanInetUnitNetCmdMove→**部隊移動**（+現位置 (x,y)，欄位對位已驗・座標為候選語義）、CSanInetPhaseEndCmd→**階段結束**、建造類顯示**城池名＋座標**（city_id_table）、出征兵種/兵力、接納仕官「對象#」；移除誤導欄「勢力 ID」；「unsupported class」噪音清零。③build_dist 補 `backend/city_id_table.json`（先前未入發行包）。④31/31 測試（+1 新測）；dist `fengye-omni-hub-0.2.14.zip`；Hub 重啟（PID 60313）；replay 驗證 render_error=null、本局 49 條指令全可讀。

- **0.2.15（2026-10-18 12:5x，用戶要求「在風夜 Hub 上加建控制」）**：①**新分頁「風雲・本機控制」**（風夜操控台內）：登入大廳→進遊戲（直連、線路可選）／退出遊戲（溫和：STOP+SIGTERM helper）／強制關閉（wineserver -k）／重新整理狀態；**勢力切換（開局後・實驗）**：讀取目前狀態、切到 0–7、還原上一個——全部走本機 `backend/fengyun_local.py`（staging 自動就位：`~/sgi-direct-connect/collector-bridge`＋`fengyun_setforce.py`；wine＋`sgi-py32.exe`）。②**房間監控頁新增「實驗室新流程」按鈕列**：一鍵武裝並進房（`arm_now.sh`＝清場→登入→進房→20 補丁→藏身→守望＋Hub 記錄器）／實驗室收線（`stop_shadow.sh`）／查看狀態（進程、D8 回執、崩潰台帳、app.log 尾）——走新模組 `backend/lab_remote.py`（一發式 `ssh host bash -s`；**刻意不進 `backend/server.py`**，維持與 web hub 的逐位元組一致釘子）。③版本 0.2.14→**0.2.15**；**31/31 測試**；`build_app.py` 重建＋重啟（PID 87530）；dist `fengye-omni-hub-0.2.15.zip`（322 檔）。④原則不變：本機控制僅操作本機風雲客戶端（prefix-sikarugir10），**不讀玩家記憶體情報、不觸碰風夜隱身層**。

- **0.2.16（2026-10-18 12:3x，用戶回報「沒看到風夜成功切換勢力」）**：根因＝0.2.15 的勢力切換按鈕是「**本機風雲**」的（用戶寫入 1＝風雲自己，故無可見變化；**風夜的切換在遠端**、且被 slotkeep 鎖定）。①新遠端助手 `shadow/shadow_force.sh`（`read`｜`switch N`｜`restore`；switch＝停 slotkeep→`shadow_setforce --slot N`→**以新席位重啟 slotkeep**）。②Hub 新 box「**風夜・遠端勢力切換**」（風雲・本機控制頁）：讀取風夜席位／切到 0–7／還原——走 `lab_remote` 一發式 ssh（`bash -s`），結果就地格式化為「席位＋勢力表」。③**實測**：風夜由席 1（風雲18）→**席 0（丁滿11）**（`written`／`now=0`、slotkeep(0) 執行中、roundprobe `my_slot=0` 兩採樣穩定）。④版本 0.2.15→**0.2.16**；**31/31 測試**；`build_app.py` 重建＋重啟（PID 1833）；dist `fengye-omni-hub-0.2.16.zip`。

- **0.2.17（2026-10-18 12:5x，用戶要求「數值→該勢力名稱＋玩家名」）**：根因＝**現行 `shadow_session_rec.py` 只解到 class_name、未解 cmd7 席位**（舊 room_probe 流程有解，故 10/16-17 會話有席位；10/18 起的影子會話全缺）→ Hub 的「會話席位」與勢力表為空。修正：①錄製器接上 `p28_wire`（`inspect_object`＋`decode_snapshot`）：**CSanInetInitGameData 幀即時解出 `snapshot`**（8 席＋settings；consumed==length，尾差自動修剪）；②**回填當前局**（已捕獲的 754B cmd7 解碼後追加 received_packet 行，evidence_type=backfill_decoded_from_native_slot）；③端到端驗證：remote_snapshot 讀出 `snapshots.start`＝**丁满・宋(11)／风云・巴(18)／電腦 楚(4)中山(15)羌(21)吴(8)赵(1)南蛮(19)**；④Hub 勢力表格式化：`0→丁满・宋（id 11）`；電腦席位＝`2→電腦・楚（此席操控欄無值）`（局面快照 binding46 ↔ 運行欄 f4a 分開呈現）。版本 0.2.16→**0.2.17**；31/31 測試；build_app＋重啟（PID 35369）；dist `fengye-omni-hub-0.2.17.zip`。⑤錄製器本體 repo／遠端 tools 同步（新 sha 待記）；**p28_wire.py 已部署遠端實驗室根目錄**。

- **0.2.18（2026-10-18 13:2x–13:4x，用戶指示：標籤收攏＋操控台精簡，開始逐項驗收）**：①**移除三分頁**——「本局局勢」「房間與來源記錄」「風夜指令解讀」（遊戲記錄顯示由全知情報來源承擔）；主視窗收攏為**唯一可見分頁「風夜操控台」**（原版 15 分頁維持 hidden）。②連帶刪除：情報流／會話席位快照／聊天日誌卡／回放按鈕／解碼表與其渲染路徑（`render_feed`／`select_feed`／`render_legacy`／`render_decoded`／`pick_replay`）＋`update_control_state` 的舊 `room_button` 引用；資料讀取錯誤訊息改集中到操控台底部新 `notice_label`。`native_window.py` 1272→1047 行。③`run.py` 驗證器改為：唯一可見分頁＋三個子分頁（房間監控／發言與回執／風雲・本機控制）逐個可視＋原版分頁全 hidden。④**驗證**：單元測試 31/31；回放 `--verify-json` 通過（render_error=null、selected＝風夜操控台、子分頁 viewable=[true,true,true]、原版分頁 15/15 hidden）；README 同步改寫；dist `fengye-omni-hub-0.2.18.zip`（322 檔，sha256 `2d2d2131…`）；.app 重啟（PID 11250）。⑤附註：13:28 曾出現一版並行操作的 0.2.18 打包（含尚未修正的舊 run.py）；本輪已以修正後源重打包覆蓋（同版本號、以新 sha 為準）。⑥下一步＝按分頁逐項功能驗收（驗收疊加）。

- **0.2.18 補記（同輪，2026-10-18 14:1x）**：影子會話錄製器 `shadow_session_rec.py` **真修**——新增 **control cmd 7 直投物件**解包（開局名單 `CSanInetInitGameData` 即時解 `snapshot` 入 hub；此類幀不走 control5 批次，13:0x 版掛鉤不可達故此前未生效）；本局（run-20261018-134329-shadow）名單已回填，席位切換框即刻顯示「0→丁满・韩（id 2）／1→风云・吴（id 8）／電腦席（此席操控欄無值）」。驗證與佈局：`research/protocol-archive/evidence/p51-control7-object-carrier-20261018/NOTES.md`；兩端 md5 `86bf4ef5…`。

- **0.2.19（2026-10-18 14:3x，用戶指示：電腦席隱去、只保留切換玩家席）**：①`_format_force` 席位表**只列可切換的玩家席**（運行欄 f4a 有效＝真人在座；-1／未知＝電腦或空席直接不列出）；無可切席位時顯示「沒有可切換的玩家席位——開局後自動出現；電腦／空席不列出」。②兩排席位按鈕（本機＋風夜遠端）改存引用，**讀取結果一到就只放行玩家席**（讀不到資料＝全部放行方便重試）。③新增模組函式 `force_payload()`＋`_update_slot_buttons()`；排行榜式顯示維持「名字・勢力（id）」。④測試 **32/32**（+1：席位過濾與按鈕放行）；回放驗證 render_error=null；README 新增「開局後控制」一節；dist `fengye-omni-hub-0.2.19.zip`；.app 重建＋重啟。⑤效果：開局後讀取顯示「0→丁满・韩（id 2）／1→风云・吴（id 8）」，電腦席不再出現。⑥驗收清單＝`ACCEPTANCE.md`（疊加式：已驗 0–4；待驗 5–13，含下一局「切換寫入」）。

- **0.2.20（2026-10-18 14:4x，用戶指示：風夜增加偽名「待秋至」）**：`native_window.py` 進房暱稱預設值 `風夜`→**`待秋至`**；預設選項改為 `['待秋至','風夜','小白']`（編輯框仍可自填）。32/32 測試通過；`.app` 重建重啟（單實例）；dist `fengye-omni-hub-0.2.20.zip`。走「進入所選房間」路徑的進房／離開痕跡將顯示「待秋至」；實驗室客戶端路徑（影子 SANPK 顯示名）另行核實處理。

- **0.2.21（2026-10-18 15:1x，用戶指示「一鍵化＋狀態明白化」）**：①房間監控新增**「▶ 一鍵上場」**（`one_click_enter`）——登入(如需)→更新房間→進入（自動報到→藏身）；複用既有重試狀態機（`retry['label']` 標籤化文案），完成自動收束、沿用提示音；已在房則拒重入；「進入所選房間」手動按鈕保留為單步。②**風雲明白狀態**：`fengyun_local.live_status()`＝**現行會話（helper.pid 對號）優先**，其次最新流程日誌結果；覆蓋 not_started／logging_in／holding（列房間）／already_logged（伺服器「已登入」友好化）／aborted／stopping／exited；`login()` 已在線短路回 `already_online`（不再送注定失敗的登入）；UI 加大字狀態行（每 ~10 秒自動刷新）。③37/37 測試（新增 5）；`.app` 重建重啟；dist `fengye-omni-hub-0.2.21.zip`；回放冒煙 render_error=null。未動主線同輪的實驗室按鈕文案改動（並存）。

- **0.2.22（2026-10-18 15:2x，用戶指示：探針層收起、只要帶客戶端的）**：房間監控頁的探針層三行（▶ 一鍵上場／手動單步排／上場前準備）**默認收起**（`probe_box` 容器 + `pack_forget`；lab 行右側「顯示探針層（進階）」開關可展開），底部說明改述客戶端完整 SOP 用法；探針功能代碼與測試全部保留（37/37 通過）；`.app` 重建重啟、dist `fengye-omni-hub-0.2.22.zip`。

- **0.2.24（2026-10-18，vkquant-com 同步）**：包含 0.2.23 玩家白話三頁介面；修正 venv 原生入口（base_prefix 標準庫＋purelib 套件）、本機控制沿用該台 Wine 的帳號／路徑／顯示名、情報台強制結束改呼叫 game-stop 保留大廳。遠端 Wine 1.22＋情報台 0.2.24 已安裝開啟；327 檔 SHA 核對、Wine 44/44、Hub 本機 50/50／遠端 49+1 比較來源缺失略過、原生三頁回放及即時來源確認。兩個現有遊戲實例 PID／啟動時間保持，未實按強退或操作遊戲。本機原生入口未重啟；日期落後維修尚未部署。詳見 `research/reports/vkquant-wine-fengye-sync-20261018/NOTES.md`。

- **0.2.28（2026-10-20，用戶指示：外部指令去掉乘數與數值輸入、目標固定風夜、地圖回歸遊戲地圖）**：
  ①`native_window.py` 外部指令面板：移除「乘數」與所有數字輸入（基礎值/extra/數量/花費金/X/Y/武將id），
  改成固定值＋按鍵（練兵 value=75、施捨 4、米交易 1000、建設花費金 2000；兵種/建築/買賣/人事子類型用下拉；
  人事武將改成下拉，來源 `command_service.general_ids()` → `_p60_generals.py` 的在野樣本）。
  ②目標客戶端固定「風夜（藏身，自動借席）」，不再有下拉（`_cmd_selected` 一律挑 風夜）。
  ③地圖改回遊戲本身的世界地圖：`assets/SanInet.lbm`（525×350）當底圖，城池/部隊按世界座標
  （WORLD=101×202 線性投影）疊上去；戰場頁與外部指令頁都套用，`<Configure>` 會重畫。
  ④驗收：`python3 -m unittest discover -s tests` 50/50；`--verify-json` 讀到新面板文字（無乘數、目標=風夜）；
  以 `FENGYE_START_TAB=外部指令|戰場` 啟動截圖確認：真實地圖＋城池名（薊/宛…）、面板無數字欄位。

- **0.2.29（2026-10-20，用戶指示：底圖要用全知情報的全景大地圖；滾輪不能一滾就跑掉；同一格不重複建設）**：
  ①**底圖換成原作地面** `app/assets/SanInet.mbm`（9744×4872、8-bit、48×24 交錯菱格），解碼走
  `app/tactical_terrain.py`（與全景地圖／城周邊同一套，唯讀、共用 mip 快取）。525×350 的 `SanInet.lbm`
  不再當底圖。載入 0.08s、1x 首繪 0.22s（mip8），放大裁切 1–17ms。
  ②**相機重寫**：`map_camera` 單一路徑 `scale = contain 倍率 × zoom`，1x 整張等比置中、放大縮小不變形、
  相機夾在底圖內；舊版 1x→1.2x 會從 1.03 倍跳到 2.15 倍（「地圖被拉走」的真因）。
  ③**投影改成菱格座標** `world_pixel(x,y)=48+96x+48(y%2), 24+24y`（格心），舊版線性 `x/101*寬` 會偏一格。
  ④**滾輪**：delta 正規化（一格 120 → 1 步，觸控板小 delta 按比例，單事件最多 3 步），且**以游標為軸**縮放
  （`map_unproject` 反算），不再「一滾內容就往游標下方滑走」。WASD 每次 10% 可見範圍、雙向夾邊界。
  ⑤**去重**：新增 `_p60_occupied.py`（建築／陷阱／城池關卡佔用格）＋ `CommandService.occupied_cells()`、
  `busy_build_cells()`（佇列＋在途 job），`validate()` 在建設前擋掉「該格已有物件／已在佇列／剛送出」；
  城池點選挑空地時也跳過已排隊的格子。遊戲端建造函式（0x4515a8 的 4/5/6 分支）本身不查佔用，
  所以同一格重複下指令會疊出第二個陷阱（畫面疊兩三條血條）——面板層擋住。
  ⑥**可讀性**：名稱重疊自動跳過、白字加深色描邊、左下角提示加深色底板、1x 地圖加邊框；
  外部指令頁共用同一套相機／投影，畫布加高到 250。
  ⑦**除錯**：`/tmp/hub-map-debug.log` 每行帶時間，記錄 terrain 載入、每次 draw 的 canvas/zoom/scale/cam/box；
  繪圖若拋例外會寫 traceback 並在畫布上顯示「地圖繪製失敗：XxxError」（不再留一塊黑畫布）。
  ⑧驗收：`python3.14 -m unittest discover -s tests` 96/96（新增 46 條地圖＋去重測試）；
  `docs/panel-20261020-terrain-1x.png`、`-2x.png`。

- **0.2.30（2026-10-20，用戶指示：繼續解決地圖的移位問題）**：
  ①**真因找到了**：「一滾就下移」不是算式錯，是**相機夾邊界**錯。戰場畫布比底圖寬
  （1164×362 vs 9744×4872 → 3.2:1 vs 2:1），1x~1.7x 之間「可見寬度」大於底圖寬度，
  舊版在這種情況把水平相機**釘死在底圖中央** → 水平軸完全不吃游標錨點，
  游標底下的地圖會橫向跳走（實測一格滾輪最多 **64 px**）；垂直軸那時已經可以自由移動，
  兩邊行為不一致，使用者看到的就是「地圖歪掉、往下移」。
  ②**修法**（`map_clamp_axis`）：相機中心永遠落在底圖上——可見範圍比底圖小就夾在底圖裡，
  比底圖大就讓底圖在畫布裡滑動（游標錨點照樣成立）。縮放後把相機中心夾到新倍率的合法值
  再存回去，舊的「想去的中心」不會留在地圖外。實測：單格滾輪位移 108 px → **0.05~0.19 px**。
  ③**上一窗「無法重現」的工具是壞的**：用 `withdraw()` 的隱藏視窗時，Tk 的
  `event_generate('<MouseWheel>')` **根本不會送進 binding**，量到的「沒有位移」是假象。
  改成已對映的視窗才量得到真實事件（這也是本次能定位真因的關鍵）。
  ④**滾輪節流** 40 ms（跟 `app/panorama_map.py` 的全景地圖一致）：觸控板一個手勢會送
  十幾個小事件，沒有節流倍率會直接衝到上限。
  ⑤**新增拖曳平移**（按住地圖拖）：跟全景地圖一致，1 畫布像素 = 1/scale 個底圖像素。
  ⑥外部指令頁共用同一套相機，1x 置中 view 不變；提示改「拖曳／WASD 平移」。
  ⑦驗收：`python3.14 -m unittest discover -s tests` **107/107**（新增 11 條回歸測試：
  單格／兩格滾輪錨點、相機不再釘死、相機中心不離地圖、節流、拖曳）。
  舊版夾邊界下這 11 條會失敗（實測 56 px／124 px 位移）。
  ⑨**畫布幾何診斷**：`battle canvas geom=...` 寫進 `/tmp/hub-map-debug.log`
  （scrollregion / xview / yview / image item 座標 / winfo 高），
  區分「相機算錯」與「Tk 畫布自己捲了／畫錯位置」。

- **0.2.31（2026-10-20，GPT 接手完成地圖展示修復，使用者實機確認正常）**：
  ①更正上一窗「不是 Tk 捲動／疑似合成」結論：無 scrollregion 時，`yview=(0,1)`
  仍可有 `canvasy(0)=-396`；圖塊與所有標記因此整層下移，並非截圖漏抓。
  ②可重現根因是漏接 Tk 9 `<TouchpadScroll>`；原版隱藏全景地圖安裝的
  `map_navigation._class_touch → _fallback_scroll` 對戰場 Canvas 呼叫 `yview_scroll`，
  每次把原點移動 36px。既有 `<MouseWheel>` 回傳 break，但擋不到這種獨立事件。
  ③戰場改用全景地圖同一個 `bind_pointer_wheel`（含 packed touchpad、修飾鍵、
  Linux 滾輪），保留相機游標錨點／節流／拖曳；外部指令小地圖也消化捲動事件。
  `map_lock_viewport` 在 Configure 時以畫布內框限制 scrollregion，兩軸原點固定 0。
  ④新增 7 項已對映 Tk 端到端測試：舊版 6 項失敗（實測 -36/-432px），
  新版總計 **115/115**；合成事件測試只遮蔽無關的實體游標位置，不 withdraw 視窗。
  ⑤正式 .app 已重建／重啟 0.2.31，使用者確認「已正常，地圖不再下沉」。
  日誌新增真正 canvas origin。驗收圖／跨平台與發行核驗見 `docs/map-display-0.2.31.md`；
  Windows 原生 GUI 未實測。未動遊戲進程、存檔或實驗室鏈。

- **0.2.32（2026-10-20，指令即時隊列／主地圖建設／原作全景與持續讀取）**：
  ①僅七按鍵：練步／騎／弓，以及兵營7／馬房8／弓房9／陷阱6。練兵立即建立 canonical job。
  建設直接在外部指令主頁原全景地圖顯示全部己方城池可建綠框，沒有城池按鈕列或Toplevel；
  單擊只選格，按「確認位置並加入隊列」才入隊。同樣本terrain_grid沿用radius4/type2規則，
  排除真物件與busy；重疊格按距離/cityid歸城。成功立即鎖格、切勢力/類型/局/失效清選格。
  ②隊列三頁僅顯示真game_key相同且非legacy記錄，無key/異局只留本機audit，不再自動匯入。
  真身分key跨面板重啟穩定且不重播；準備、等phase後與baseline後核局。未知agent同process
  即使core改變仍擋後續；Collector無獨立局ID，同process/core/劇本/名單完全重用仍有識別限制。
  ③未有代送副作用的指令可撤回；arming起不冒稱可安全撤回。同勢力批次、異勢力串行、同兵種
  待前筆真變化。玩家視角顯示真玩家/勢力/城名、訓練值及金前後變化；不露rc/狀態碼/核心位址。
  ④本機回執不算完成。完整同來源原始新快照且capture_start晚於receipt_at，確認訓練增加或
  同格同勢力同類型唯一新建物件才completed；未知不重送、不自行解除待發門檻，建設格保留。
  ⑤入口 **fengye_battle_panel.py** 勿改回會撞app/battle_panel.py的名稱。原renderer保留城池/
  兵種sprite/旗/補給/格線/HP士氣；隱藏對手狀態、上方filters/定位/產兵；陷阱固定True、僅文字
  可勾選，zoom深色字。兩頁3秒背景singleflight讀shadow-only，共用cache，失效不回退真人端。
  ⑥自有logo/PNG/ICO/ICNS位assets及prompt，不改遊戲/Wine圖標。發行包明確白名單＋SHA，
  附兩支只讀lab helper；本機data/config/遊戲/存檔/憑據不打包。
  ⑦最終測試及實際已對映畫面見docs/command-map-0.2.32.md；本輪Mock指令＋真唯讀地圖，
  **未實送新遊戲指令，不宣稱新版代送已實局端到端成功**。Windows原生GUI未實測。未改遊戲
  或存檔，不新增HANDOFF。

- **0.2.33（2026-10-20，開局自動讀取／原版勢力頁／建設原生格位）**：
  ①正式run路徑bridge優先，root command_effects撞名導致_binding ImportError。專用檔改名
  fengye_command_effects，子程序回歸覆蓋真launch順序；兩頁3秒自動讀取，持續顯示例外也不堵讀取。
  ②重掛原版勢力情報／對比widgets：手牌原圖、信望、庫存、訓練／城武將／內政等，依shadow
  同源快照更新；pack(in_)後需lift/lower，否則雖mapped卻被console蓋白。topmost＋實際截圖已驗。
  頂部是本次真觀測幀數，非回放落檔證明；原始全勢力內政輸入未完整捕獲，空白不代表未下令。
  ③建設原錯是column-major地形誤用row-major，且radius4/type2不符原生。現在單一純規則
  _p60_construction_rules供Hub與Winehelper共用：交錯距離3、設施0/1/2、陷阱另7..19、
  動態佔用／控制勢力、鄰接城關／交戰兵、逐城旗標／陷阱數等。linkedcity照原容器首個符合。
  _p60_construction_grid唯讀包裝Collector同capturepagecache讀tile+c/e兩張signed16表，不
  寫遊戲、不將動態值留在staticcache。四helper白名單發行，本機已備份部署且SHA一致。
  ④原地圖淡藍半透可選、hover白框、選取金框；點格→明確確認→入隊保留。未高亮不再逐格
  顯示不可選/未知。既有同類設施原版可增建，但sender尚未驗證，先排除以免疊物件。原本機
  全域待發陷阱context未完整捕，保留未知，不能用0或各城pending和代替，位置高亮非全額度證明。
  ⑤最終287/287；真已對映原生screencapture-l與唯讀自動幀核對見docs/live-and-construction-0.2.33.md。
  未實送新遊戲指令、未動遊戲/存檔；Windows原生GUI未實測。

- **0.2.34（2026-10-20，代送閘門修復：內政期內直接發送／落後偵測／不再跨回合借席）**：
  ①**實局失敗**：15:23:21 第一筆（73,21，陷阱）下單時風夜 phase=1；Hub 依原設計等「本回合
  結束」→15:24:18 切到燕席位→15:24:24 武裝「只在 phase=1 發射」；風夜之後停在 phase=4
  （結算）、season=0，主機／風雲已到 phase=1、season=3，agent 永遠等不到 phase 1；
  15:29:24 回執逾時→unknown，後 5 筆 held。證據見 docs/command-gate-0.2.34.md。
  ②**主修**：`_wait_for_domestic_phase` 取代 `_wait_phase_exit`。若下單時已在內政期（phase=1）
  **立即切席、武裝、發送、還席**，只在內政期內持有借席數秒，不再跨回合邊界；
  非內政期則**不切席**地等 phase 1（`phase_wait_timeout` 150→600 秒），可撤回。
  ③**落後偵測**：新增 `reference_state()` 讀本機真實玩家（prefix-sikarugir10，退回
  prefix-dingman-local）的 phase/season；`_staleness_error()` 在 shadow season < 真實 season
  且 roster 相同（同一局）時，**切席前**直接 error：「代送客戶端停在 season 0…玩家端已在
  season 3」；等待中每 20 秒重比，真實端前進而風夜不動就提早失敗。不同 roster 不比，
  避免跨局誤判。無本機真實端時跳過（遠端主機仍可代送）。
  ④**切席後複查**：切席約需數秒，若期間已離開 phase 1，立刻還席並 error（不武裝），
  避免把借席帶進下一回合。⑤**還席家修正**：`_ghost_home_slot()` 先沿用
  `slot_pending_restore` job 的 `slot_home`，不再把 slotkeep 的目標玩家 `--slot` 當家。
  ⑥**回執逾時說明**：`_wait_receipt` 逾時時重讀 phase/season，寫入 `stall_note`
  （停在 phase=4、season=0 或落後訊息），`progress_text` 的 unknown 直接顯示，不再只有
  「結果待確認」。
  ⑦**驗證**：`python3.14 -m unittest discover -s tests` **293/293**；新增 current-phase
  直接發送、切席前落後拒絕、等待中真實端超前中止、不同 roster 不誤判、pending job 保留家
  等回歸。**真唯讀**讀數：shadow (phase 4, season 0)、reference (phase 1, season 3)，失敗
  訊息正確。⑧**限制**：本局風夜已停擺且局中不能重入；舊 unknown job 仍會擋同進程新單，
  需風夜換進程。**本輪未實送任何遊戲指令**；same-IA 代送需下一局實測才算端到端成功。
  未動遊戲/存檔；Windows 原生 GUI 未實測。

- **0.2.35（2026-10-20，版面放大／預計遊戲時間／實驗室掉線鈕／同盟聊天說明／風夜全域去霧）**：
  ①**版面**：`display_layout` 預設上限 1280x900→**1400x1000**（1710x1107 螢幕實得
  1400x967）；外部指令頁地圖請求高度 320→**380**；隊列列高 3→2、詳情 2→1 行、周邊 padding
  收窄；「勢力／立即讀取」與自動讀取狀態同列（狀態靠右），建設提示移入地圖頁腳。
  ②**預計執行遊戲時間**：`CommandService.eta_text(phase, year, season)` 以真實玩家端
  （reference）的 `f_4d0`/`f_4d6` 計算；phase=1 →「YYYY年X內政階段（現在）」，
  phase≥2 → 下一季「YYYY年X內政階段結束後」，phase=0 → 本季。隊列新增
  **「預計執行（遊戲時間）」**欄（job.eta_text），詳情頁同步顯示。年份/季節讀值由
  `_read_targets` 帶入；reference 由外部指令頁每 60 秒快取一次（背景執行緒）。
  ③**實驗室掉線鈕**：新可見子分頁「實驗室」，內含目標下拉（丁滿／風雲）、
  「讓對手掉線」紅色鈕與「檢查本機客戶端」。呼叫 `CommandService.drop_client(prefix)`
  → lab `tools/p63_drop_inject.py`（一發 ExitProcess）；每次 `askokcancel` 二次確認，
  失敗不重試；風夜不可作為目標。**未實按**（破壞性），只驗按鈕/服務參數。
  ④**聊天歷史**：頁首加註「只顯示風夜連線收到的聊天；同盟／私聊是否可旁聽尚未驗證
  （P60）」；目前 type-3 本地投遞＋公開 Chat 可見，同盟頻道未經實測不宣稱可攔。
  ⑤**風夜全域去霧**：本局 one_click_test 未裝 p52 godview（`fog_original=true`）。已對
  當前 shadow（PID 1456）以 p52 UI 交易安裝 **map-tiles + map-unit-sight + 5 個
  detail/skin**（`ui-state-godview.json`，全部 `enabled`）；`shadow_status` 現回
  `fog_original=false`、`godview.installed=true`。此為 lab 執行期補丁，**不進發行包**；
  重開客戶端後需重裝（`arm_now.sh` GODVIEW=1 已含 22 元素流程）。
  ⑥**驗證**：`python3.14 -m unittest discover -s tests` **296/296**（新增 eta 格式、
  submit 保留 eta、drop 目標限制/p63 參數）；本機 .app 重啟 0.2.35，外部指令頁截圖
  `docs/command-page-0.2.35.png`。未實送遊戲指令、未按掉線鈕；Windows 原生 GUI 未實測。

- **0.2.36（2026-10-20，代送歸屬修正：本機玩家自己的勢力改由本機客戶端直接送出）**：
  ①**實局證據**：16:05:27–16:05:41 四筆建設（actor 3 丁滿·齊，魯縣）全部收到本機回執
  （rc=1、phase=1、own=183165165＝風夜 id），但主機狀態 186 棟 production_buildings 中
  目標格（73,63/73,65/74,64/74,65）**沒有新建物**；受控讀 host `_p60_battle.py`（改帶
  `SGI_GAME_EXE`/`PYTHONIOENCODING`）確認。判定：**隱身風夜沒有應用行，主機以 sender id
  找不到席位而丟棄 domestic 指令**；rc=1 只代表本機 SendObject 成功，不等於主機執行。
  ②**修正**：`CommandPanel._sender_for_force()`——若目標勢力是 slot 的暱稱「丁满」→
  `prefix-dingman-local`、「风云」→`prefix-sikarugir10`，`auto_slot=False`（由真實客戶端
  直接送，不切風夜席位）；其他（非本機玩家／電腦）才 fallback 風夜借席。payload 帶
  `sender_label`，job/detail 顯示「送出：丁滿（本機直接送出）」。
  ③**服務路徑**：`_run_batch` 的 `auto` 只在 `auto_slot and prefix==shadow` 成立；直接
  客戶端走非 auto：讀該 prefix 的 phase、無切席、agent 在該 prefix 發射、回執/效果照舊
  由 shadow 快照驗證。`submit` 的 target pid 對直接 prefix 為 None，`_prepare_job` 以
  `self.pid(prefix)` 重新確認。
  ④**測試**：**298/298**（新增 panel 三勢力 sender 映射、丁滿 force 走本機 client、
  service 直接 batch 不切席）。⑤**注意**：16:05 那四筆已進入 `verifying`（本機回執、
  主機無效果），不重送、不自動取消；要用新路徑**重新下單**。未實按掉線鈕；Windows
  原生 GUI 未實測。

- **0.2.37（2026-10-20，使用者定案：一切只准風夜客戶端執行；面板改為只放行風夜自己的勢力）**：
  ①**使用者否決 0.2.36**：丁滿／風雲本機客戶端只可用於內測輔助驗証，正式執行必須由風夜
  客戶端完成，包括收聊天紀錄。②**面板強制**：`CommandPanel._ghost_force()` 讀 snapshot 的
  `local.force_id`；`_enqueue` 只放行 `force_id == 風夜自己的 force`，其他一律拒絕並在
  note 說明「這不是風夜自己的勢力…風夜送主機會丟棄」；藏身／旁聽（local force=None）時
  任何指令都拒絕，提示「風夜目前沒有勢力」。payload 固定 `prefix-fengye-shadow`、
  `auto_slot=True`、`sender_label='風夜（自己的勢力）'`。`_read_targets` 新增 `local`。
  ③**根因（實局證據）**：主機的 domestic 指令處理與聊天一樣，以 **sender id 對應用行**；
  藏身風夜只有 DLL 成員、沒有應用行 → 4 筆 rc=1 但主機 186 棟 production_buildings 無
  目標格新建物；`风云: hi` 在風夜 session 68 幀中 **0 幀**。這不是 Hub 顯示或閘門問題，
  是應用層路由只認有行的成員。④**可行路線**：風夜必須以**有席位的玩家**（偽名可見）入座，
  拿到自己的勢力；此時它可以用自己的 sender id 送**自己勢力**的指令、並收到投給應用行的
  公開聊天。要送丁滿／風雲的勢力＝冒用他們的 session id（伺服器端認證）或改主機，屬紅線，
  需使用者另行裁決。⑤**測試**：**299/299**（新增只放行風夜自己勢力、藏身無 force 全拒絕；
  移除 0.2.36 的面板直接 client 期望）。⑥未實送指令；下一步需以 `one_click_test.sh --no-hide`
  讓風夜入座取得勢力，才能做風夜-only 的實局驗証。

- **0.2.38（2026-10-20，session-id 冒用兩發實測：frame spoof＋host member 表 patch 均 negative；面板改為「入座後可借任何勢力」）**：
  ①**第一發（P57 agent_spoof，broadcast）**：`--spoof-id 167872591`（丁滿）、54B domestic
  指令；receipt `magic=39474853 rc=1 own=183165165 target=167872591 len=54`。主機金仍
  **37,233**、`production_buildings` 仍 **186**、目標格無新建物 → 未套用。
  ②**第二發（agent_uplink + spoof，to host）**：`magic=37474853 rc=1`、同一 payload、
  spoof 167872591；主機仍未扣金／無建物。
  ③**host member 表 patch**：掃到 host 進程 16 處風夜 id；把 `0x2702210` 與 `0x2701ed0`
  兩處成員 id 由 183165165 改成 167872591，再送 p60 指令；主機仍未套用；**已寫回
  0xaeae0ed 還原**（readback 確認），host 金/建物未變。
  ④**判定**：主機的 domestic 指令 gate 不只在 frame sender／member id；**sync roster
  （+84c4/+84c8，host 2 人：丁滿/風雲；風夜不在）+ 應用行**才是 gate。藏身 D8 風夜只有
  DLL 成員、沒有應用行、也不在 sync roster → 任何 frame/member id 冒用都不會套用。
  ⑤**面板調整**：`_ghost_force()` 仍用 `local.force_id`；藏身（None）→ 全拒絕；
  **已入座（有 force）→ 允許選任何勢力**，交由 `_run_batch` 的借席切到目標 slot，
  `sender_label='風夜（借目標席位）'`。這樣下一局風夜以 no-hide 入座＋P33 同步參與後，
  可直接從面板選丁滿/風雲測試；不再需要本機玩家 client。
  ⑥**測試**：**299/299**（入座可借任何勢力、藏身全拒絕）。⑦**未完成**：私聊／他人聊天
  仍受同一 gate（host 依 member/session 投遞）；session-level 接管（中繼/loader 用目標
  session id）尚未實作。實測與下一步程序見 docs/ghost-takeover-0.2.38.md。

- **0.2.39（2026-10-20，Hub 合成指令「先切席位再送」＋藏身可排隊；myforce 補丁為真兇）**：
  ①**使用者定案**：不要在遊戲介面切來切去，Hub 外部指令要直接走合成指令。②**真兇**：一鍵
  開局守衛 `patch_start_nulls.py` 的 `myforce` 兩站（`0x445E98`、`0x445FE3`）把風夜本地
  force 壓成 None；退回原版 6 bytes（`0fbf48083b4d`）後 slot 1 的 `local.force_id=3`
  （風雲·齊）verified、面板出現、P58「切席→點界面→切回」成功（風雲端同步看到騎兵）。
  ③**面板改動**：藏身（`_ghost_force=None`）不再拒絕；下單時先 `service._switch_slot(目標
  slot)`（**內政階段開始前**切好），再 submit；服務維持 0.2.38 的等 phase 1→切席（同席）
  →送→還席 5。合成指令只有在席位先於指令階段建立時才會被主機採納（P58/10-19 實證）。
  ④**教訓**：實時採集（幀數）與指令 worker 是兩條路；採集活著不代表 worker 沒卡（本次
  7 筆春季陷阱卡在「等待前筆確認」，主機 traps=0、金未扣 → 前筆根本沒套用）。
  ⑤**測試**：面板隱身排隊測試更新；隊列/面板單元測試（GUI 的 laptop 測試在離屏 Tk 下
  會卡 until，屬測試環境問題）。⑥**操作**：一鍵後、開局前若沒退 myforce，風夜會沒勢力；
  `ghost_takeover.sh` 待補。合成指令送出的驗收一律看主機 production_buildings/traps/金，
  不看訓練度。

- **0.2.40（2026-10-20，同一建設多格連點＋同格再點取消）**：
  ①`build_picker.EmbeddedPicker` 新增 `selected_cells`（有序）；`_click` 對候選格 toggle：
  未選→加入、已選→移除；非候選格＝清空整批（沿用舊行為）。②`_update_selection` 顯示
  「已選 N 格（最後 x,y）」，確認鈕在 N≥1 時可用；`_draw_overlay` 把所有選取格畫金框與座標。
  ③`_confirm` 逐格呼叫 `on_select(city,x,y)`（＝`CommandPanel._confirm_build`→`_enqueue`），
  每格拆成一筆獨立 job；成功格進 local_pending/candidates 移除，失敗格留在原選取。
  ④測試：`tests.test_build_picker` **47/47**。⑤使用者需求：一次點周邊多個同類建設、確認後
  自動拆分；同格再點一次＝取消該格。⑥未動服務層與合成指令 gate。

- **0.2.41（2026-10-20，Hub 合成指令改走風夜 probe 的 P40 D5 成員上傳）**：
  ①**關鍵靜態結論（p40_d5_inject.py 開頭）**：主機批次收集「不驗證成員上傳的 sender」，
  成員以自己 member id 上傳 control5（D5）會被直接併入批次；p60 的 `0x42a7d4 SendObject`
  standalone 才會被 sender/sync 檢查丟棄。這解釋 P58 UI 生效、p60 合成失敗。
  ②**probe 端早已內建橋**：`p34_d8_probe.py --control-file/--control-result/
  --d5-authorization-file`；`op:"d5"` → `domestic_record(**record)` → `D5Gate.reserve`
  → `send_reliable_native`（`4c80`+`4b60`）→ result JSON。
  ③**Hub 新增 `probe_sender.py`**：`build_record(job)`（54B 同構：actor/parameter=建設種類/
  value=城池/extra/operand=(y<<16)|x/subtype=4）、`ProbeSender.ids(host_pid)`（讀主機
  member table 取風夜 id 與房主 id）、`arm()`（P40 receipt：contract=P40/enable_d5/
  test_game_confirmed/own_id/host_id/observed_wall）、`send()`（寫 control JSON、等 result、
  回 raw_rc/target，逾時不重送）。
  ④**CommandService**：`_run_batch` 偵測 `sender=='probe'` 即走 `_run_probe_batch`
  （不借席、不等 phase、不跑 p60 agent；baseline→arming→send→fired→verifier）。
  ⑤**面板**：`_enqueue` 固定 `sender='probe'`、`auto_slot=False`，移除 0.2.39 的
  「先切席位」；label「風夜（probe D5，免切席位）」。
  ⑥測試：`tests.test_probe_sender` 6/6；panel hidden/seated 2/2（laptop 測試在離屏 Tk
  仍會卡 until，屬測試環境問題）。
  ⑦**未完成**：本局風夜是 SANPK（非 probe），舊批次用 `agent_uplink` 送的 D5 已到 host
  （rc=1 own=181506542 target=179754453 len=70）但停在 200 秋 phase 3，需推進回合才能
  驗 production/gold；probe 版端到端要等新一局（probe 當風夜）才能驗。

- **0.2.42（2026-10-20，probe 風夜一鍵與交付）**：
  ①新增 `~/sgi-fengye-lab/shadow/one_click_probe.sh`：probe 風夜版一鍵（headless 進房→
  使用者開局→cmd9→sync→D8 摘席→被動旁聽），帶 `--control-file/--control-result/
  --d5-authorization-file/--d8-authorization-file/--execute`，控制檔與 Hub `ProbeSender`
  完全對齊（`hub_control.json`/`hub_control_result.json`/`hub_d5_auth.json`）。
  ②**使用順序**：使用者建房→`one_click_probe.sh <主機IP>`（SHADOW_USER=待秋至）→使用者開局→
  probe D8 摘席→Hub 外部指令按建設/練兵→Hub `_run_probe_batch` 寫 control→probe D5
  （`4c80`+`4b60`）→主機批次併入→結算後讀 production/traps/金。
  ③**已知限制（必須如實告知）**：probe 是 headless，沒有遊戲地圖記憶體；Hub 的
  `targets`/`battle`（金、cities、兵）目前仍讀 SANPK 影子。probe-only 局只能從 probe 的
  p28 wire 取席位（cmd7）/指令（control5）/聊天；要完整局面需另一個唯讀旁聽端。
  ④交付狀態：Hub 0.2.42 已建置重啟；`test_probe_sender` 6/6、panel hidden/seated 2/2。
  **端到端未驗**：本局（SANPK 風夜）的 D5 批次已到 host（rc=1 len=70）但停在 200 秋
  phase 3；probe 版需新局。未宣稱合成指令已實局生效。

- **0.2.43（2026-10-20，合成指令改走「遊戲按鈕自己的送出函式」／D5 判死）**：
  ①**靜態定案（P64，`research/ai/p64-ui-send-chain-20261020.md`）**：所有 UI 指令按鈕
  （練兵 `0x4A3BA8`、建設、人事…）最後都走 **`0x446482(world, &cmd)`** → `0x42A7D4`
  （序列化）→ `_NetMsg_SendCmd@8`。成員端 `_NetMsg_SendCmd` 送的是 **control 4**
  （單筆、sender 由連線決定），不是 control 5。Koeinm 的型別分派（`0x10003CD0`）：
  type4 只給 **host** 收（append 進 0x84BC 批次）、type5 只給 **member** 收（主機廣播批次）。
  ⇒ **成員上傳 control5（D5）永遠進不了主機**，與「收集窗口」無關；P40 的
  「不驗 sender」只適用 control4（sender 由連線決定，無法偽造）。
  ②**agent 新 ui 模式**（`p60_generic_cmd_build.py` blob 0x1D0=1）：`0x34`=0x446482、
  `0x38`=0x44B83B；送出前以 **本席勢力**（`0x44B83B(core)`）填 `cmd+0x14`，並與
  `expect_actor`（blob 0x1D4）比對，**席位不符就不射**（避免借席失敗時記到別人勢力）。
  `p60_generic_cmd_inject.py --ui-path [--expect-actor N]`；agent bin 682B、
  sha256 `e32c8934…`（repo＋lab tools 同）。
  ③**Hub**：`build_args` 固定帶 `--ui-path --expect-actor <目標>`；面板 `_enqueue`
  回到 `auto_slot=True`、`sender='agent'`、label「風夜（借目標席位 → 遊戲按鈕函式）」，
  不再用 probe D5（probe 分支保留為死路，不再被面板選到）。
  ④**驗證**：`test_p60_generic` **25/25**（+5 條 ui 模式：blob 佈局／只呼叫 0x446482 一次／
  this=core-0x912／actor 跟席位／席位不符拒發）；`tests.test_probe_sender` 6/6；
  面板 hidden/seated 3/3。`tests.test_command_queue` 仍有 3 條 **本輪之前就失敗** ＋1 條卡住
  （已用「移除本輪改動」對照確認），整份 `_run_batch` 有重複區塊待整理。
  ⑤**未實機點火**：本輪沒有新局、沒有注入任何 client；「ui 模式實局生效」未驗，
  驗收仍看主機 production_buildings/traps/金。未改遊戲 EXE/存檔；Windows GUI 未測。

- **0.2.44（2026-10-20 23:0x，實局首發成功／WASD 全域按鍵）**：
  ①**實局第一發**（200 年春內政、風夜借 slot 0＝漢）：`arc` 回執 `rc=1`、`kind=18/subtype=4`、
  `operand=0xC2003B`（x=59,y=194）、`f14=20`（actor 由席位取得）、`f18=6`、`f1c=43`、`f20=2000`；
  時序 pending→validating→switching_slot→**arming→3 秒 settle→fired（22:02:22）**→restoring（還席 5 成功）。
  主機端 traps/gold 需**內政階段結束**後才看得到，尚未驗收。
  ②**修 `_run_batch`**：前幾輪留下三段重複區塊＋未定義的 `preborrowed`，任何批次都在切席後
  NameError（22:52 六筆陷阱全卡）。重寫成單一路徑；`tests.test_command_queue` 由 3 失敗＋1 卡死 → **33/33**。
  ③**修 agent 相位閘門**：`Sleep(settle)` 之後用被清掉的 EAX 跟 phase 比 → 永遠不相等、永不發射
  （22:55 那筆只能等 300 秒回執逾時）。改為 `mov eax,[esi+0x148]` 重讀；新增 settle 回歸測試，
  `test_p60_generic` **26/26**。agent bin 688B、sha256 `48dca4…`。
  ④**WASD 修好**：按鍵只綁在 canvas，焦點跑到按鈕／隊列表／下拉就失效。改成 **每個 toplevel 一組
  `<Key>` 派送**（`_claim_keys`／`_dispatch_key`），路由到最後使用的地圖；文字輸入框（Entry/Text/
  Combobox/Treeview/Listbox）不攔。註冊表用 `id(toplevel)`（同名 `.` 的新視窗不會吃到舊綁定）。
  `tests.test_map_events` **9/9**（新增「焦點在按鈕仍可 WASD」「Entry 裡打字不移動地圖」）。
  ⑤整份套件：`python3.14 -m unittest discover -s tests` **307/307**（修掉一條仍期待 probe/auto_slot=False 的面板測試）。
  ⑥**「開局前上身」按鈕（0.2.44 追加）**：進房與準備頁新增「開局前上身（風夜席位）」＝
  slot 下拉（0–7）＋「套用（要在按『開始』之前）」；後端 `CommandService.switch_ghost_seat(slot)`
  只呼叫 `shadow_force.sh switch N` 並回讀 slot→force 對照（不武裝、不送指令）。實測限制：
  **主機在按「開始」那一刻就決定席位→勢力**，開局後才切只改本機視角（今天的 23:02/23:11
  兩發就是這樣：送出成功但主機收集陣列 `collect_84c0` 一直 0）。`tests.test_command_queue` 34/34。
  ⑦**23:3x 實測突破：「開局前上身」是關鍵**（同一局 200 年春、主機 pid 32、風夜 slot 0＝force 15）：
  - 開局前用 Hub 新按鈕把席位釘在 slot 0，按「開始」後**不切席、不還席**；
  - agent 送一筆 alms（`--ui-path --expect-actor 15`）→ 回執 rc=1 → **主機 `collect_84c0` 0→1**；
  - 對照：23:02/23:11 的「開局後才切席＋送完還 5」兩發，主機 `collect_84c0` 一直是 0；
    風雲用同一支 agent 送則立即 0→1（證明 agent 本身無誤）。
  ⇒ 主機收不收，取決於**風夜在開局那一刻是否已坐在該席位**，不是指令格式、也不是名冊人數
  （主機名冊始終 2）。因此 `_run_batch` 新增：`local.force_id == actor` 且 `local.slot == slot` 時
  **跳過切席與還席**（`already_seated` 事件）；面板在已上身時 `auto_slot=False`、label
  「風夜（已上身 → 遊戲按鈕函式）」。`tests.test_command_panel + test_command_queue` 53/53。
  ⑧**23:5x 兩個定論**：
  - **換走再換回沒問題**：先確認 `collect_84c0=0` → `shadow_force.sh switch 5` → 10 秒 → `switch 0` → 送 alms →
    主機收集陣列第 4 筆就是它（`field0=179123277`、kind 18 subtype 2、actor 15）。
    所以身份是**開局那一刻**建立、之後可自由離開/回到席位（重啟 slotkeep 約 10 秒）。
    差別只在「開局後才第一次上身」無效（23:02/23:11）。
  - **下單硬閘門**：`CommandService.pre_seat`（由「開局前上身」按鈕寫入 `{slot, game_key}`）；
    `validate()` 對 shadow 指令要求「本局有 pre_seat 或 local.force_id == actor」，否則拒絕：
    「這一局沒有在開局前上身…請先按『開局前上身』再下單，否則主機會丟棄」。
    `tests.test_command_queue` **35/35**（新增無 pre-seat 拒絕）。
  ⑨**00:0x 跨勢力完整落地（決定性）**：風夜開局前上身 slot 0（中山 15）→ 局中 `switch 1`（羌 21，風雲那席）
  → Hub 下「陷阱＋練弓」→ 主機收集陣列 8 筆中含 rec6（subtype 4、operand (10,75)、actor=21、
  parameter=6、value=53、extra=2000）與 rec7（subtype 0、actor=21、parameter=2、value=75），
  另 rec5 是客戶端自己出兵的 `CSanInetUnitNetCmdCreate`。結算後主機：
  - **trap (10,75) owner=21**（Hub 的陷阱真的蓋出來）；
  - **羌 弓訓練 0 → 15**（Hub 練弓生效）；
  - 羌 弓兵 0 → 1000（客戶端出兵）；
  - 羌金 50160 → 47220。
  ⇒ **身份不綁勢力**：開局拿到任一有勢力的席位後，可自由切到別的席位替那家下單，主機照做。
  只有「開局後才第一次上身」無效。`local.force_id` 與 `pre_seat` 兩條閘門都按此設計。
  ⑩**0.2.48 開局後自動回無勢力**：使用者要求「開局前上身 → 開局後自動切回無勢力(5)」。
  `CommandService.should_auto_restore()`（純判斷）＋`_read_targets` 讀到 `local.force_id` 有值、
  且該局有 `pre_seat` 紀錄時，背景執行緒呼叫 `_switch_slot(5)`，**每局只做一次**
  （`_restored_games`）。進房頁該列新增勾選框「開局後自動切回無勢力(5)」（預設開）。
  之後下單走原本的借席流程（切到目標→送→回 5）；身份已實測不受切換影響。
  測試：`test_command_queue` **36/36**（新增 should_auto_restore 六種情形）、面板 19/19。
  待實測：掛在 slot 5 時風夜的世界是否仍隨主機推進（agent 相位閘門吃風夜自己的 phase）。
  ⑪**0.2.49 外部指令頁實時身份狀態**：外部指令頁在「勢力／立即讀取」下方新增一行
  「**風夜目前：無勢力（旁聽）**／**風夜目前：羌（force 21，slot 1）**」，每次自動讀取
  （3 秒）更新；無勢力灰色、有勢力用強調色。搭配 0.2.48 的自動回 5：預設常駐無勢力，
  下單時服務自動借目標席位→送→回 5。`test_command_panel + test_command_queue` 55/55。
  ⑫**0.2.50 pre-seat 紀錄持久化＋自動認定**：使用者回報「沒有加入：這一局沒有在開局前上身」。
  根因＝`switch_ghost_seat` 當下 `current_game_key` 可能是 None（還沒讀過），記成
  `{game_key: None}` → 永遠比對不到。修：①按鈕切席時若 key 空，先 `targets(refresh=True)` 取；
  ②寫 `data/pre_seat.json`、Hub 重啟後 12 小時內仍沿用；③`_read_targets` 看到「phase 0（開局前）
  且風夜已在有勢力席位」就自動記為該局的 pre-seat（等於按了按鈕）。測試 55/55。
  ⑬**0.2.51 切席錯過內政不再直接失敗**：00:19:48 那筆（義渠陷阱）在 00:19:59 切席、00:20:11 完成時
  內政已結束 → 舊邏輯「切席後已離開內政階段」直接判 error＋還席。改為：**保留席位、等下一輪內政**
  （最多 `phase_wait_timeout`）再發；等不到才還席並報錯。測試 36/36。
  同時確認：該局風夜**沒有身份**（00:19 的 alms 探針 actor=13 本機 rc=1，但主機 `collect_84c0`=0）
  ——因為它是開局後才上身的；要驗指令必須「按開始之前」先按套用。
  ⑭**0.2.52 自動認定改成「有 key 且風夜在座就記」**：0.2.50 的自動認定條件寫成 `phase == 0`，
  但大廳階段根本還沒有 game_key（席位表顯示「勢力 -1」），所以永遠記不到 → 使用者按了套用、
  進局後下單仍被閘門擋。改為：只要有 `game_key` 且 `local.force_id` 有效就記一次（同一局只記一次，
  真正驗收仍看主機 collect）。測試 36/36。
  ⑮**0.2.53 切席跨回合導致客戶端卡住 → 明確報錯**：00:25 那筆（風雲·蜀陷阱）在 00:25:25 切席
  （12 秒），剛好跨過春→夏邊界；之後風夜客戶端**停在 season 0（春結算）**、主機已 season 1（夏），
  它的內政永遠不來 → agent 一直等。跟隨取樣：`host ph3 seas1 ｜ ghost ph3 seas0`。
  修：切席後的等待圈每輪比對 reference，發現風夜落後就**還席＋明確報錯**（不再掛到逾時）。
  教訓：**切席不要跨回合邊界**；要下單就在內政前段（或趁結算時先把席位切好），
  結算中切席（23:40 那次）是安全的，內政尾聲切席（本次）會把客戶端卡住。
  ⑯**0.2.54 「進房後自動上身」成為默認補丁（使用者要求）**：進房頁該列新增勾選框
  「**進房後自動上身**」（預設開）；一鍵完成、風夜已藏身（`ghost_withdrawn`）後，
  `_maybe_auto_seat()` 自動 `switch_ghost_seat(下拉的 slot)`（預設 0），每間房只做一次
  （以房名為 key）。使用者此後只要「一鍵 → 按開始」，不用再手動按套用。
  同輪把「開局後自動切回無勢力(5)」**預設關閉**：開局那一刻再花 12 秒切席最容易把客戶端
  卡在舊季節（見 ⑮）。外部指令頁的勢力下拉也改成「沒明確選過就默認風夜現在坐的那家」，
  這樣下單不需要切席。測試 native+panel+queue 全綠（62 項）。
  ⑰**0.2.55 全部改默認、不再有勾選框（使用者要求）**：進房頁刪掉兩個勾選框，改一行說明
  「默認：進房後自動上身 → 開局 8 秒後自動回無勢力」。自動上身每次一鍵開始都重設守衛
  （修正 00:31 那局被一鍵最後一步 slot 5 覆蓋的問題）。自動回 5 加兩個條件：
  **只在 phase 1（內政）切**、且**開局後至少 8 秒**（`auto_restore_delay`）——避免 12 秒的
  切席跨過回合邊界。測試 queue+panel+native 全綠。
  ⑱**0.2.56 無勢力狀態分兩種顯示**：外部指令頁那行現在會分辨「有沒有身份」：
  - `風夜目前：無勢力（旁聽）· ✓ 本局已取得身份（可下單）`（綠）
  - `風夜目前：無勢力（旁聽）· ✗ 這一局沒有身份（下單會被主機丟棄）`（紅）
  - `風夜目前：蜀（force 5，slot 0）· ✓ 已上身`（強調色）
  資料來源＝`_read_targets` 新增的 `out['pre_seat']={'ok','slot'}`（比對本局 game_key 是否
  有 pre-seat 紀錄）。這樣「上身後切回無勢力」與「一開始就無勢力」在畫面上不會再混在一起。
  ⑲**0.2.57 自動上身改在「一鍵完成」當下觸發**：00:37 那局一鍵完成後風夜仍在 slot 5 →
  因為舊的 watcher 靠房間狀態輪詢（fresh/connected/ghost_withdrawn）才動作，狀態還沒 fresh
  或 room_busy 仍為真時就錯過了。改成：`retry_next()` 走到 `if not steps`（一鍵成功收尾）
  時直接呼叫 `_auto_seat_now()`（背景 thread → `switch_ghost_seat(下拉 slot)`），
  watcher 保留為備援。測試 native 通過。
  ⑳**0.2.58 手動「套用」整個移除**：進房頁只剩一行說明「默認：一鍵完成後自動上身 slot 0
  → 開局 8 秒後自動回無勢力」；slot 下拉與「套用」按鈕、`apply_pre_seat` 全部刪除。
  自動上身固定 slot 0，仍由一鍵完成時觸發（0.2.57）。測試 native+panel 通過。
  ㉑**0.2.59 「↻ 重新來過」搬到可見列**：該按鈕原本放在 0.2.22 預設收起的探針層裡，
  進房頁看不到。移到「讓風夜進房／風夜下線／查看風夜狀態／卡住了？強制結束」那一列。
  測試 native 通過。
  ㉒**0.2.60 有指令在排隊/武裝時不得切回無勢力**：00:46 那筆（丁滿·蜀 陷阱 39,109）在 00:46:39
  武裝，接著「開局 8 秒自動回 5」把風夜拉回無勢力 → agent 以本席勢力填 actor，席位變成 -1
  就永遠等不到符合的席位 → 卡在 waiting_phase、主機 collect=0。
  修：`should_auto_restore(..., busy=)`，`busy = has_active_jobs()`；有 pending/arming/fired/
  verifying 等狀態時不切回 5，等指令全部結束才回。測試 36/36。
  ㉓**0.2.61 跨季未完成自動作廢（使用者要求「下一季還沒下到就是有問題，直接清空」）**：
  ①`_prepare_job` 記 `due_season = season + (0 if phase==1 else 1)`；`_read_targets` 每輪呼叫
  `_expire_stale_jobs(season)`：狀態仍在 ACTIVE_STATES 且 `season > due_season` → `error`
  「跨季未完成…已自動作廢，可重新下單」。②手動「撤回」對 `結果待確認`/`已武裝` 是刻意停用的
  （不能安全撤回），所以卡住的單目前只能等自動作廢；00:46 那筆已人工作廢（agent blob 的
  sent 旗標寫 1、ledger 標 cancelled）。測試 36/36。
  ㉔**0.2.62 轉向：不再從 Hub 下單（使用者定案 2026-10-21 02:0x）**：
  ①**下架「外部指令」「戰場」兩個分頁**（`control_book.hide`；元件與服務保留，因為
  `switch_ghost_seat`、pre-seat 仍用得到）。②進房頁新增「**開局綁定**」下拉：
  `無勢力（不綁定）` 或 `玩家 1..8（slot 0..7）`，**預設玩家 1（slot 0）**；一鍵完成後
  依此綁定（`bind_slot()` → `_auto_seat_now`）。③**取消「開局 8 秒自動回無勢力」**——
  `auto_restore_after_start` 預設 False（服務與 UI 都關）。④指令改在遊戲客戶端直接下，
  跟隨回合的問題用「快速軍令」面板處理（另一支程式）。
  測試 native+queue 通過。
  ㉕**0.2.63 綁定用玩家真名＋切換速鍵**：①`CommandService.room_players()` 讀影子客戶端的
  app rows（`p32_app_rows_read.py`，輸出是 `tables[*].rows`，欄位 `i`＝slot、`name`＝暱稱），
  `_env` 補 `SGI_BRIDGE_Z` 否則 `probe` 模組匯入失敗。②進房頁「開局綁定」下拉改成
  「丁满（slot 0）／风云（slot 1）…」，每 15 秒刷新、排除風夜自己、同 slot 去重。
  ③新增「切換速鍵」列：`無勢力` ＋ 每個玩家一顆，按了立刻 `switch_ghost_seat(slot)`。
  測試 native 通過。
