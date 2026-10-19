# P59 免界面合成命令（kind 18 訓練）：逆向完成 + 一發 agent 已備妥

日期：2026-10-19 晚 ｜ 現場：**無對局**（使用者 20:05 開的那局於 20:28:24 自行結束，見 §8）
前置文件：`HANDOFF_20261019_免界面合成命令.md`（本輪只做第 3 節「下一步」）

---

## 0. 一句話結論

訓練指令的「合成」路徑已完全打通：**用遊戲自己的建構子造 `CSanInetDomesticCmd`，
交給遊戲自己的送出函式 `0x42A7D4`**（＝ 界面路徑的最後一步），線路位元組與真實對局
擷取到的訓練指令**逐位元組相同**（有黃金樣本可比）。一發式 agent + 注入器 + 一次性
發射腳本 + 離線/實機靜態驗證全部就緒，**只等新局點火**（本輪未發任何幀、未開局、未動存檔）。

---

## 1. 對交接文件表格的三處修正（重要）

| 交接文件寫的 | 實際 | 證據 |
|---|---|---|
| `CSanInetDomesticCmd` ctor = `0x4369DB` | `0x4369DB` 是 **`GetRuntimeClass()`**（`mov eax,0x5334b0; ret`，vtable[0]）。**真 ctor = `0x4369F6`**（0x24 bytes），由配置器 `0x4369A9`（`push 0x24; call operator new`）呼叫 | `0x4369f6` 反組譯 |
| 「type `0x533554`」 | `0x533554` 只是**類別名字串** `"CSanInetDomesticCmd"`；`0x5334B0` 才是 `CRuntimeClass` 記錄 | 讀 .data |
| 「Serialize 在 vtable 槽」 | vtable `0x5039F8` = `[0]=GetRuntimeClass 0x4369db, [1]=scalar deleting dtor 0x436a22, **[2]=Serialize 0x436a6f**, [3]=AssertValid(空), [4]=Dump(空)` | 讀 .rdata + `0x4D5A29` 的呼叫序 |

**這是一套 MFC-CObject 風格的可序列化命令族**（`CObject` + `CRuntimeClass` + `CArchive`），
所以 `0xFFFF / schema / name` 的類別標頭與 `body` 都是框架產生，不是手寫的。

`0x5334B0` 的內容（唯讀實測）：

```
+0x00 name        0x533554  "CSanInetDomesticCmd"
+0x04 objectSize  0x24      (36 bytes)
+0x08 schema      1
+0x0c factory     0x4369A9
+0x10 base class  0x533408  (CSanInetCmdObject)
```
同族：DiplomacyCmd size 0x33 @0x5334C8、PersonnelCmd 0x1C @0x5334E0、PhaseEndCmd 0x14 @0x5334F8。

---

## 2. 欄位圖（`CSanInetDomesticCmd`，size 0x24）

| offset | 類型 | 意義 | 由誰寫 |
|---|---|---|---|
| +0x00 | ptr | vtable `0x5039F8` | ctor |
| +0x04 | i32 | **kind = 18** | 基底 ctor `0x4359E7(18, …)` |
| +0x08 | i32 | **subtype**：0 訓練／2 施捨／3 米交易／4 建設／5 拆除／8 偵察 | 同上 |
| +0x0c | i32 | 動作操作數（4/5/8 時是壓縮地圖座標 XY） | 同上 |
| +0x10 | ptr | 基底字串（空字串單例 `0x53AC40`），序列化為 **1 byte = 0** | 基底 ctor |
| +0x14 | i32 | **actor = 勢力 id**（ctor 預設 −1） | 界面／agent |
| +0x18 | i32 | **parameter = 兵種** 0 步／1 騎／2 弓（訓練） | 界面／agent |
| +0x1c | i32 | **value** | 界面／agent |
| +0x20 | i32 | **extra**（界面填 `KOEItlbm Func0302()&1` 的隨機位） | 界面／agent |

`Serialize = 0x436A6F`：先 `0x435A44` 基底（3 個 i32 + 1 byte 空字串），再依序
`+0x14 / +0x18 / +0x1c / +0x20`（經 `0x417188` = `operator<<(int)`）。
反序列化是同一個函式、方向由 `stream+0x14` bit0 = 1 決定（走 `0x4171E1`）。

⇒ **body = 29 bytes**（12 + 1 + 16）；加類別標頭 `FFFF 0001 1300 "CSanInetDomesticCmd"` 後
**整筆 = 54 bytes**，與 `bridge/native_command_evidence.py` 的 `(18, 29)` 完全一致。

---

## 3. 「我的指令」交給網路層的那個函式 = `0x446482`

界面按一次練兵（`0x4A3BA8`）的實際順序（本次逐條核對）：

```
0x4369F6                      ; 在堆疊上造 DomesticCmd（this=ebp-0x68）
[ebp-0x54] = force_id         ; +0x14 ← 0x44B83B(core)  = *(core+0x4a + slot*0x87)
[ebp-0x50] = 按鈕兵種          ; +0x18
[ebp-0x48] = Func0302()&1     ; +0x20
[ebp-0x4c] += 兵力累計         ; +0x1c ← 0x45C6E3(unit,1)
0x446482(G, &cmd)             ; ← ★「我的指令」交出去的那一步（G = core-0x912）
```

`0x446482` 本體（`ret 4`，`this` 在 ecx）：

```
446482: andl $0, 0x80(%ecx)     ; G+0x80 = 對局閘門（roundprobe 的 gate_G80）歸零
446490: call 0x430ED2           ; 取靜態 CSanInet 成員位址 0x53B540
446499: +0x132 → 0x53B672       ; 該成員的 this
4464a0: call 0x42A7D4(this, cmd); 送出
4464a5: movl $1, (%esi)         ; G+0x80 歸一
```

`0x42A7D4`（＝ `CSanInet::SendObject(CObject*)`）：

```
0x4DACCB / 0x4D60E6  建 CArchive（0x400 buffer / 0x1000 記憶體檔）
0x4D5A29            ar << pOb  → 取 vtable[0] 寫類別標頭、再 call vtable[2] Serialize
0x42A7AC            SendCmd(buf,len)
0x42A7AC → IAT 0x4FB460 = Koeinm `_NetMsg_SendCmd@8`（成員分支 → 0x10002450 入隊）
```

**這就是 P57 硬塞封包失敗、而界面點擊成功的分界**：P57 走的是底層 `0x4C80/0x4B60`
（可靠提交），沒有經過 `_NetMsg_SendCmd` 這條「命令」語義的入口。

> agent 的取捨：直接呼叫 **`0x42A7D4`**，不呼叫 `0x446482`。
> 線路位元組完全相同，但**不會去動對局閘門 G+0x80**（回執同時記錄 before/after 以證明這件事）。
> 若未來需要完全照抄界面路徑，只要把 blob 的 `send` 換成 `0x446482`、`send_this` 換成 `G` 即可。

---

## 4. 一發 agent（`agent_domestic.bin`，445 bytes，sha256 `079cd2ca…`）

流程（只做一次，之後永久靜默）：

1. 閘門：觸發檔存在 → `_NetMsg_IsConnected@0` ≠ 0 → `[0x53BB30]`（core）≠ 0 →
   `core+0x6C0`（my_slot）≤ 7 → actor 0..31 → parameter 0..2 → own id ≠ 0。
2. `lea ecx,[esp]; call 0x4369F6`（**遊戲自己的 ctor**，物件在 agent 堆疊上）。
3. 寫 `+0x14/+0x18/+0x1c/+0x20` = actor / parameter / value / extra。
4. `mov ecx, 0x53B672; push &obj; call 0x42A7D4`（**遊戲自己的送出**）。
5. 立刻把 once-only 旗標置 1（在任何 I/O 之前，避免重複發射）。
6. 寫 48-byte 回執：`magic/rc/core/actor/parameter/value/extra/tick/gate_before/gate_after/phase/own`。
7. 之後 1 秒一輪 sleep，不再發任何東西。

工具鏈（本機 lab 與 repo 鏡像 SHA 全同）：

| 檔案 | 作用 |
|---|---|
| `tools/p59_domestic_cmd_build.py` | agent 組譯（clang i386）+ blob 佈局 + 黃金線路 + 靜態錨點檢查 |
| `tools/p59_domestic_inject.py` | 注入器（Wine py32）：單發紀律、SANPK 3.5 錨點預檢、`--plan` / `--check` |
| `tools/p59_domestic_selftest.py` | 在 Wine py32 裡跑「不碰遊戲進程」的自檢（匯出表＋磁碟映像錨點＋黃金線路） |
| `p59_domestic_fire.sh` | 一發腳本：注入 → touch 觸發檔 → 解回執（可 `PLAN=1` / `CHECK=1`） |
| `tools/test_p59_domestic.py` | 15 項測試（含 unicorn 行為模擬，見 §6） |

---

## 5. 線路黃金樣本（可直接比對）

真實對局擷取（2026-10-17 15:32:40，actor=7、步兵訓練、value=95、extra=1）：

```
ffff 0001 1300 "CSanInetDomesticCmd"
12000000 00000000 00000000 00          ; kind=18 subtype=0 operand=0 空字串
07000000 00000000 5f000000 01000000    ; actor=7 parameter=0 value=95 extra=1
```

本輪 `expected_wire(7,0,95,1)` 產生**逐位元組相同**的 54 bytes（`test_golden_matches_real_capture`）。
要打「替勢力 12 練騎兵 value=95」時，預期線路是：

```
ffff000113004353616e496e6574446f6d6573746963436d6412
00000000000000000000000000 0c000000 01000000 5f000000 00000000
```
（`0c000000` = actor 12、`01000000` = 騎兵、`5f000000` = 95、`00000000` = extra 0）

---

## 6. 驗證（本輪實際跑過）

* `test_p59_domestic.py` **15/15 通過**（venv `~/.venvs/fengye`，unicorn 2.1.4）：
  * 黃金線路 == 真實擷取；長度/欄位/範圍；
  * blob 佈局 lock；回執 round-trip；
  * **unicorn 行為模擬**：ctor 以合理 `this` 被呼叫、`0x42A7D4` **恰一次**、
    物件四欄位 = (12,1,95,0)、kind=18/subtype=0、once-only 旗標、閘門前後不變、
    回執 12 欄位逐一比對；
  * 閘門負測：無觸發檔／core=NULL／slot=9／actor=99／own=0／已發過 → **都不發**；
  * 靜態錨點（對**實機** `SANPK.exe`，sha256 `df9b5225…a8eea`）：vtable[0]/[2]、
    `CRuntimeClass` name/size/schema/factory、ctor prologue。
* Wine py32 自檢 `p59_domestic_selftest.py`：**ok=true**（匯出表 `IsConnected=0x20B0`、
  `GetIPAddress=0x22B0`；磁碟映像四錨點全過；黃金線路與 blob 352 bytes 正常）。
* 註：P51/P57 舊測試套件在本機原本就因 evidence 目錄路徑漂移而報錯（`agent-build` 不存在），
  與本輪新增檔案無關；P59 套件全綠。

---

## 7. 待實機（需使用者開新局；本輪**未**點火）

前置：三台在跑、風夜藏身（slot=5 無勢力）、處於**內政（指令）階段**。

```
# 0) 只讀預檢（不寫入任何東西）
PLAN=1 bash ~/sgi-fengye-lab/shadow/p59_domestic_fire.sh 12 1 95 0

# 1) 訓練前讀值（宋=11、鲁=12 的步/騎/弓訓練度）
wine python.exe .../tools/lord_read_any.py <風夜 wine pid>

# 2) 一發（actor=目標勢力，parameter=1 騎兵，value=95）
BEFORE=1 bash ~/sgi-fengye-lab/shadow/p59_domestic_fire.sh 12 1 95 0

# 3) 請主機結束回合，再讀一次 → 訓練度 +N 即成立
wine python.exe .../tools/lord_read_any.py <風夜 wine pid>
```

驗收四條：
1. 回執 `rc=1`、`gate_before == gate_after`、`phase` 落在指令階段；
2. 主機 control5 批次出現一筆 `CSanInetDomesticCmd`（actor = 目標勢力、parameter = 兵種）；
3. 回合結束後目標勢力**該兵種**訓練度上升、其他勢力不動；
4. 三台讀值逐欄位一致、`roundprobe` 四件套正常推進、崩潰台帳無新增。

失敗模式與對策：
* 回執沒出現 → 看閘門（斷線／core 為空／slot 越界／已發過）；不會有任何重試。
* `rc=0` → `_NetMsg_SendCmd` 回錯誤碼（記在 `this+0x10`，agent 只記 rc）。
* 主機批次沒有這筆 → 主機端對「發送者不在同步名單」的過濾（P57 的結論指向這裡）；
  對照組＝先切視角派單（P58 B1 已成功）確認同一 actor 走界面可進批次。
* 批次有但訓練度不動 → `value` 語義問題（見 §9）。

---

## 8. 現場狀態（本輪未動）

* `~/.venvs`、lab、repo 三處 SHA 已核對。
* 使用者 20:05:18 開的那局（Hub pid 432）於 **20:28:24 自行結束**（`game-status.json`
  `event=exited, code=1`），本輪第一個 wine 指令在 20:34 之後才出現，**與本輪無關**；
  目前 `ps` 看不到任何 SANPK.exe，所以沒有任何對局可測。
* 本輪**沒有**發任何遊戲幀、沒有注入任何進程、沒有開局、沒有動存檔或 EXE。

---

## 9. 未定項（照實列出）

1. **`value` 語義未證**：唯一樣本 value=95；候選＝金／兵力／訓練度相關量。界面是從
   選定部隊物件 `+0x28`（u8）累加並 clamp 300。首發先照抄 95，用「+N 是否等於界面點一次」
   來反推。
2. **`extra` 語義未證**：界面填 `Func0302()&1` 的隨機位；首發填 0。
3. **主機是否只看 actor、不看發送者**：P58 B1（藏身、無勢力、切視角派單成功）強烈支持
   「只看 actor」，但那次的 sender 仍是風夜的會話；本輪 agent 的 sender 亦同，故風險低。
4. **指令是否必須在內政階段落地**：界面有 `phase==1` 與「我的回合」的前置檢查，agent 沒抄
   這兩個檢查（刻意），回執記 `phase` 供判讀。
