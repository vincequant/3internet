# 0.2.33 原生建設可選格：靜態證據

2026-10-20。這份記錄只研究原版程式的選址規則，沒有開新遊戲、操作遊戲介面、發送軍令、寫遊戲記憶體或改 EXE。分析結果交由建設選址模組使用；不等於新軍令已在實局成功。

## 已確定的原因

舊 Hub 的「方形半徑 4、只准地形 2」不是遊戲原生規則。至少有三處具體差異：

1. `terrain_grid.types` 是 **column-major**，格 `(x,y)` 的索引是 `x * height + y`。按 `y * width + x` 會查到別處的地形。
2. 新建兵營／馬房／弓房的基本地形允許 **0、1、2**，還有物件、鄰城、部隊、已排軍令等條件。不能只看地形 2。
3. 建設範圍使用交錯座標距離，城池的距離上限是 **3**，不是方形四格。陷阱另有自己的地形與敵軍鄰接條件，不能共用設施地形判斷。

## 來源與可信度

本機已交付、只讀分析的實際影像：

- `~/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/SANPK.exe`
- SHA256：`df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea`

倉庫反組譯來源：

- `research/protocol-archive/disasm/SANPK.exe`
- SHA256：`c081ba0c3199027359062fb7c72329bc72c37d85ca594313c1eaf1212c7747f4`
- 留存反組譯：`research/protocol-archive/disasm/sanpk-full.objdump.asm`
- 重讀工具：`research/client/protocol-lab/pe_static.py`，僅用 PE 位址換算及系統 `objdump`。

兩個整檔 SHA 不同，但下列所有分析範圍的機器碼逐 byte 相同。REA provider 狀態確認沒有可用的 Ghidra／Hopper／IDA；沒有為此安裝或改服務設定。以下規則是已交付二進位的靜態觀察；距離及枚舉另由選址 worker 用 Unicorn 離線執行相同機器碼核對。

## 點擊確實經過可選 mask

`0x498811` 是地圖點擊路徑。`0x498998` 將世界座標交給 `0x46dafd(view+0x94c,x,y)` 查 mask 成員；不在 mask 就不執行建設 handler。`view+0x948` 是當前 placement mode。

| 軍令參數 | 原生名稱／Hub 名稱 | mask builder | placement mode | click handler |
| --- | --- | --- | --- | --- |
| 7 | 練兵所／兵營 | `0x4a5826..0x4a5ad4` | 3 | `0x4a7b0a(x,y,7)` |
| 8 | 牧場／馬房 | `0x4a5ad5..0x4a5d83` | 4 | `0x4a7b0a(x,y,8)` |
| 9 | 弓工坊／弓房 | `0x4a5dab..0x4a6059` | 5 | `0x4a7b0a(x,y,9)` |
| 6 | 陷阱 | `0x4a6731..0x4a69d9` | 9 | `0x4a8117(x,y,6)` |

`0x4a7194` 把 mode 寫入 `view+0x948`，把 `view+0x94c` 各點轉成地圖高亮。故上述 builder 是實際點選集合，不是另找的相似距離函式。

## 原生座標、範圍與物件欄

`0x4348c2(city,x,y)` 呼叫 `0x46a0f7` 算距離，再與 `city.vtable+0x138` 比較：

```python
def native_distance(x1, y1, x2, y2):
    # 遊戲地圖的非負座標。
    return max(abs((2*x1 + y1 % 2) - (2*x2 + y2 % 2)), abs(y1-y2))
```

城池 vtable `0x503688` 的 `+0x138` 指向 `0x433bbb`，回傳 3（`6a0358c3`）。關隘 vtable `0x5037d0` 該位置指向 `0x434ae6`，回傳 1。不過 **關隘不提供建設候選範圍**：設施 builder 要 `virtual+0x10c != 0`，陷阱要 `virtual+0x110 != 0`；城池兩者回 1，關隘兩者指向 `0x4837bc` 回 0（`33c0c3`）。不能因關隘距離為 1 就把四周亮成可建。

候選點由 `0x46a2a5(grid,point_array,city_x,city_y,radius)` 產生，按地圖邊界裁切。內部預留 `2*r*(r+1)+1` 點；r=3 的未裁切集合有 25 點，包含城中心。中心及四個直接鄰格之後會被其他條件排除。選址 worker 離線核對：距離 leaf 共 568 組；枚舉函式僅 mock CArray 配置，五個中心、r=0..5 共 30 組，輸出集合全等於 `native_distance <= r` 且在圖內。沒有執行遊戲進程。

原生四鄰（`0x46a197 -> 0x46a3d6`，步長表 `0x506728`）：

| y 奇偶 | 四個鄰格 |
| --- | --- |
| 偶數 | `(x,y-1)`, `(x-1,y-1)`, `(x-1,y+1)`, `(x,y+1)` |
| 奇數 | `(x+1,y-1)`, `(x,y-1)`, `(x,y+1)`, `(x+1,y+1)` |

原生 tile 欄位彼此不同，不能把地形與物件碼混為一談：

| tile offset | 型別／意義 | 證據 |
| --- | --- | --- |
| `+0x08` | 格上部隊計數 | `0x469900`；`0x450102(...,1)` 先測它才查部隊 list |
| `+0x0a` | 基本地形，有號 byte | `0x469593` |
| `+0x0c` | 控制勢力，有號 word，-1 為無 | `0x4695b2` setter；陷阱 predicate 直接讀它 |
| `+0x0e` | 物件碼，有號 word；-1 無物件 | `0x4695a6` setter；`0x44b306..0x44b477` 重建 |

物件碼重建：城 0／1，關隘 2；`core+0x574` 另一物件類別為 3；圈套 4／5／6；生產設施 7／8／9。3 的顯示名稱不在本次定案範圍。

## 新建設施 7／8／9 的精確選格條件

以 7 的 builder 位址為代表，8／9 同構：

1. 內政 phase=1（doc+0xdea）；原生 view 可輸入 `0x49b0e3` 為真；本地規劃狀態 `context=doc+0x611` 有可用武將（`context+0x10 != 0`）。
2. context 可用金至少 1000 才能進設施 placement；新空格分支另要求 **至少 2000**（`0x4a58e9`）。此值是本機規劃投影的可用金，不可把它直接等同 lord 的原始金，既有規劃軍令會扣該投影。
3. 逐 owned city／barrier list：`virtual+0x68 == 0`，即 `word(city+0x22) & 0x1000 == 0`（`0x434085`）；`virtual+0x10c != 0`，排除關隘。
4. 枚舉該城距離 <=3 的圖內格。
5. `0x46986b(tile)` 為真：
   - `tile.object_kind == -1`；
   - `tile.terrain_base in {0,1,2}`；
   - `0x469923(tile) == 0`：四鄰中沒有物件碼 0／1／2。這項排除任何勢力的城／關鄰接，不看鄰城所屬。
6. `0x44fd3c(core,x,y,&kind,1)` 回填 kind 必為 0；有同格部隊為 kind1，有同格物件為 kind2。物件查詢涵蓋城／關、物件3、生產設施及圈套。
7. `0x444915(context+0x15c,x,y) < 0`：該座標沒有本機已排的建設項目。

`0x46986b` 失敗時還有原生 **增建分支**：同格物件碼等於當前 7／8／9，`0x44fe88` 取得生產建築，`0x473e6b` 要 `building_ui_amount < 15000`。它只需金1000，不走新空格分支。這是原生支持增建的證據；本輪 Hub 的送出與效果驗證僅支持新物件，不能據此把增建格顯示成「可新建」。應明確標示「已有設施／增建尚未支援」。

## 陷阱 6 的精確選格條件

builder `0x4a6731..0x4a69d9`：

1. phase=1、view 可輸入、本機有可用武將；另外 `doc+0xd7e != 3`。後者在本次僅保留精確欄位條件，不為其狀態名稱補猜測。
2. 本機規劃可用金 >=2000。
3. 全域圈套額度 `0x44527b(context)`：

   ```text
   context.pending_traps(+0x1f4) + context.owned_traps_count(+0xd0)
       < 5 * context.owned_cities_and_barriers_count(+0x70)
   ```

4. 每個來源城 `virtual+0x68 == 0`，`virtual+0x110 != 0`（故關隘不提供候選），且 `0x4349e0(city) < 5`。
5. `0x4349e0 = city.virtual+0x140(0) + dword(city+0x3b)`。`+0x140` 對城指向 `0x434240`，掃 core 圈套 list，計算 `trap.linked_city_id(+0x16) == city.id(+0x0a)` 的**所有 4／5／6 圈套**。`city+0x3b` 是本機此城已排圈套計數，型別為 DWORD，不能只讀一 byte。
6. 枚舉該城距離 <=3 的圖內格。
7. `0x4698fb(tile)`（跳至 `0x4698aa`）為真：
   - `tile.object_kind == -1`；
   - 基本地形屬 `{0,1,2} ∪ {7..19}`；後一段由 `0x404d27 -> 0x404d45/0x404d67` 確認上下界；
   - `0x46998d(tile,tile.control_force,1) == 0`。控制勢力 -1 時直接不擋；否則掃四鄰部隊，若鄰兵所屬 lord 與控制勢力不是同一勢力，且**鄰兵勢力對控制勢力的外交值為1（戰爭）**，即排除此格。外交查詢方向是鄰兵 lord → tile 控制勢力，不是當前 actor → 鄰兵。`0x46839f` 的 `dec/neg/sbb/inc` 返回 `relation == 1`，不是 `relation != 1`。
8. 同格部隊／物件 kind=0，且本機已排建設座標不存在，與設施第6／7點相同。

陷阱沒有呼叫設施的 `0x469923` 鄰城檢查，不能把該條件搬給陷阱。

全域 pending 與各城 pending 不能無證假定相等：成功排圈套時 `0x4a8215` 增 city DWORD+0x3b，`0x4a8241` 增 context+0x1f4；但 context 重建 `0x444c2c -> 0x444d78` 清全域 pending，city pending 由 `0x434798` 另一流程清除。未捕獲 context pending 時必須保留未知；不能補0，亦不能聲稱由各城和已完整重建原生本機規劃狀態。

## linked city 與「最近城」的差別

原生不是選最近城。`0x4441e1` 重建本機投影時，`0x4443a9` 取 `doc+0xe6a == core+0x558` 原始城市／關隘 list，按 owner=actor 過濾，`0x4443df` append 到 `doc+0x675` list header；此段沒有排序。click handler `0x4a7c33..0x4a7c59`／`0x4a81f0..0x4a8212` 取這個 owned list 中**第一個** `0x4348c2` 通過者，將其 city ID 寫 value 欄位。

mask 是符合條件來源城範圍的聯集，click 的 linked city 選擇卻沒有重新檢查來源城資格。在範圍重疊處，不能把生成某點的來源城直接當成原生 linked city。Hub 若依使用者的「最近城」偏好處理，應稱為 Hub 歸屬策略，不能聲稱與原生的 list-first 規則一致。

## 人口與徵兵額度是警告，不是不可選格

設施 handler `0x4a7c68` 讀 city virtual+0xb4（`0x434ce3`，population DWORD+0x3f），低於50000時改確認文字；`0x4a7c96/ca3/cb0` 讀同類 amount 合計，達到 virtual+0xfc 上限也改確認文字。兩條路都繼續 `0x4a7cdd -> 0x496e31`，訊息框回 IDYES=6 時仍產軍令。

本次直接解析實際 df9b 影像 RT_STRING：

- `0xbe9`：人口稀少時建設、增建沒有什麼效果，詢問是否繼續。
- `0xbea`：徵兵規模可能已達上限，再建造、增建沒有什麼效果，詢問是否繼續。
- `0xbf2..0xbf4`：明確稱「建設、增建」練兵所／牧場／弓工坊。

因此不能把人口不足或同類 amount 達上限當成 mask 的硬性禁止。容量計算已有 [bridge/city_production.py](../bridge/city_production.py) 的獨立證據；本次不改該公式。

## 實作與驗收邊界

- static terrain grid 可快取；`tile+0x0c/+0x0e`、部隊、圈套、city flags／pending 等為動態狀態，每個有效快照要重讀並與同源身份綁定。
- 未捕欄位為未知，不能以0、空格、無敵軍或未排隊代填。狀態不完整時，說明欠缺的選址資料，避免「已驗可建」字樣。
- 軍事階段可以先在 Hub 選址，但原生 phase=1 是實際送出前的門檻；不能因軍事階段 native placement 不啟動，就把預排畫面全部畫成地形不可建。
- 本記錄核對原生本機 UI predicate，沒有證明直接 subtype4 handler 自己會攔所有無效格。`0x4515a8` 的軍令落地與面板去重仍需保留其獨立邊界。
- 沒有實送建設、沒有對人類對局造出測試建築；最終 native GUI 實測及部署由主代理記錄，不能把此靜態／離線結果寫成實局成功。

## 可重現的機器碼綁定

下表為實際 df9b 影像對應範圍的 SHA256；與 c081 歸檔的同範圍逐 byte 相同。範圍長度明示，避免只靠函式別名重認。

| VA | 長度 | SHA256 |
| --- | --- | --- |
| `0x498998` | `0xeb` | `fbd7ef78054594e41fda4baa5a83157dedb6b5168eaaa719f475d0bd3957c29f` |
| `0x4a5826` | `0x2af` | `ab454b59f338314f42a6d181271577c4687fe1172cfdd09a652a408f4537a15c` |
| `0x4a5ad5` | `0x2af` | `c73f88df1892a837dfa2788c2faae280459fc0a777b8c1fdb55dbc908c951f56` |
| `0x4a5dab` | `0x2af` | `a5575daebe86d96ee412948ba4a510701b203dcb9ac8972f70f37fafcb8d071d` |
| `0x4a6731` | `0x2a9` | `49e79bd86189718de911b8fc0d359ca6e75c31b6afe4ee62cda3c707c0ada61d` |
| `0x46986b` | `0x1ac` | `27d6b7689e86c923832efc9231cdb15a928d6c0f22092911f52146a25f230683` |
| `0x404d27` | `0x61` | `85ce63f8f81ce7d764d01ba6931427e70fd849fef3348debbd738e1fc7cd0326` |
| `0x44fd3c` | `0x1fc` | `2ea984a6aca04edf030580db994b2fc58ec5d0ba74df8d533d6f48068ecb9220` |
| `0x450102` | `0x4a` | `ef677216dd3bb95d5f31cafbe94e12fd643ec7dc6aa9b4ec3f825404a13edf0f` |
| `0x434240` | `0x90` | `5936d43b79916e3f2a133d039cba249141258c64bc1da3273243bb07ea2c54cf` |
| `0x4348c2` | `0x52` | `f8485e468deb40e62dbfafad1771ffdb25d06502f27ce53b11bfaf0d0b079dc9` |
| `0x4349e0` | `0x16` | `c68fbd911a721beea2a52ddd1ce464d1afbdd6456a664065ed05b4ed0fe5b109` |
| `0x46a0f7` | `0x4b` | `01bfde3404c64668bd3a615db696ea4274d9c4f1f168cbdff1e1829387e01d4b` |
| `0x46a2a5` | `0xe1` | `6a95cae585226dcf3002d8ca6577d37aed7ab45488d718e0d039dadd21f1623f` |
| `0x468381` | `0x3b` | `6cbf62d690f5cc7e343309cabd129cdf7fa9f6aca77cec678e1768d7b10e47fd` |
| `0x4443a9` | `0x83` | `84d51f919e8df410dd143dbef84fa526758e99b23e73f67d08931174ad4ef41f` |
| `0x44527b` | `0x22` | `f00cc840427cfebbe63b31b362cf6f5cfe070431ea4ec32757d96505581efa36` |

重讀範例（只讀）：

```sh
python3 research/client/protocol-lab/pe_static.py \
  research/protocol-archive/disasm/SANPK.exe dis 0x4a6731 0x2a9
```
