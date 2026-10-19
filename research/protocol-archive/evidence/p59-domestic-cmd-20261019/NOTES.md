# P59 免界面合成命令（kind 18 訓練）— 證據與工具

日期：2026-10-19 晚 ｜ 狀態：**prepare only（未點火）** ｜ 對局：無（20:28 已結束）

## 這是什麼

把「切視角 → 點界面 → 切回」換成「造命令物件 → 交給遊戲自己的送出」的最後一塊：
`CSanInetDomesticCmd` 的欄位/Serialize 展開，以及界面路徑最後那一步的定位。

## 錨點（全部本輪重新核對；實機 SANPK.exe sha256 `df9b5225…a8eea`）

| 項目 | 位址 | 說明 |
|---|---|---|
| CRuntimeClass | `0x5334B0` | name=`0x533554` "CSanInetDomesticCmd"、size `0x24`、schema 1、factory `0x4369A9` |
| vtable | `0x5039F8` | `[0]=0x4369DB` GetRuntimeClass、`[1]=0x436A22` dtor、`[2]=0x436A6F` Serialize、`[3]=0x401094` 空、`[4]=0x4023AC` 空 |
| ctor | `0x4369F6` | 基底 ctor `0x4359E7(18,0,0,"")` + `+0x14=-1,+0x18=0,+0x1c=0,+0x20=0` |
| Serialize | `0x436A6F` | 基底 `0x435A44` + 四個 i32 |
| 界面叫用點 | `0x4A3BA8` | 在堆疊上造物件，最後 `0x446482(G,&obj)` |
| 交出點 | `0x446482` | `G+0x80=0 → 0x42A7D4(0x53B672,obj) → G+0x80=1`（G = core−0x912） |
| SendObject | `0x42A7D4` | `CArchive << obj` → `0x42A7AC(ptr,len)` |
| SendCmd | `0x42A7AC` | IAT `0x4FB460` = Koeinm `_NetMsg_SendCmd@8` |
| core 全域 | `0x53BB30` | `[0x53BB30]` = core（`p53_unit_data.py` 同源） |

> 修正：交接文件把 `0x4369DB` 當 ctor、`0x533554` 當 type；實際 `0x4369DB` 是
> `GetRuntimeClass()`，`0x533554` 是類別名字串。詳見 `research/ai/p59-synthetic-domestic-cmd-20261019.md` §1。

## 線路格式（黃金樣本）

真實擷取（`p48-multi-human-snapshot-20261017/run-152630-command-intel.jsonl` 第 3 筆，
actor=7 步兵訓練 value=95 extra=1）：

```
ffff010013004353616e496e6574446f6d6573746963436d641200000000000000000000000007000000000000005f00000001000000
```

`expected_wire(7,0,95,1)` 逐位元組相同（測試 `test_golden_matches_real_capture`）。

## 檔案

```
build/agent_domestic.bin        445 B  sha256 079cd2ca10025f74ae1a09079852b34cd81e5fbd14425e631c49bd5c4ab6623e
build/agent_domestic.s          agent 原始組譯（單一真相來源）
build/agent_domestic.listing.txt
build/manifest.json             blob 佈局 / 錨點 / 黃金線路
```

工具（lab `~/sgi-fengye-lab/shadow/` 與 repo `research/client/protocol-lab/` SHA 全同）：

| 檔案 | sha256 |
|---|---|
| `p59_domestic_cmd_build.py` | `7d70a5786ca237c29c99a98fb152171341eaa6a23de9d1f024a7a7136be575b6` |
| `p59_domestic_inject.py` | `c8b649781fdbbfba9b83d55290df6a11debdc14c49497e000a213e8976ac48bc` |
| `p59_domestic_selftest.py` | `a2658523bff4aface84d71854dcea46c8e210679837091ef96c664750ea2e9de` |
| `test_p59_domestic.py` | `170da9cc0759644c9872d2140dd3ccc0b1789e08865d321fcc6e606e2d2dd0b0` |
| `p59_domestic_fire.sh` | `5bb6a022e4c3582c91addb2199882b506054f07cb63a3c249938521b3709db6c` |
| `agent_domestic.bin` | `079cd2ca10025f74ae1a09079852b34cd81e5fbd14425e631c49bd5c4ab6623e` |

## 驗證

* 本地 `test_p59_domestic`：**15/15 OK**（含 unicorn 行為模擬：ctor this 合理、`0x42A7D4` 恰一次、
  四欄位正確、once-only、閘門不變、回執 12 欄位；六種閘門負測；實機 EXE 靜態錨點）。
* Wine py32 `p59_domestic_selftest.py`：**ok=true**（Koeinm 匯出 `0x20B0/0x22B0`；磁碟映像四錨點；
  黃金線路；blob 352 B）。
* 未發幀、未注入、未開局、未改 EXE/存檔/發行包。

## 點火手冊（等新局）

見 `research/ai/p59-synthetic-domestic-cmd-20261019.md` §7：`PLAN=1` 只讀預檢 →
`lord_read_any.py` 讀訓練度 → `BEFORE=1 bash p59_domestic_fire.sh 12 1 95 0` →
主機結束回合 → 再讀。驗收＝回執 rc=1/閘門不變、主機批次出現該筆、目標兵種訓練度 +N、
三台一致且回合正常。
