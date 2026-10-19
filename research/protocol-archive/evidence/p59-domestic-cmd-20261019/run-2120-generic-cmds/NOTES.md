# P60 通用合成命令：把「一種」擴成「一類」——實測 train / rice / alms 生效、phaseend 未生效

日期：2026-10-19 21:19–21:40 ｜ 同一局（run-2106 的延續，190 年）｜ 發送端：風雲（在同步名單內）

## 0. 做了什麼

把 P59 那支「只會練兵」的 agent 升級成 **通用版**：物件佈局改成 blob 裡的一張小表
（每個欄位 = offset+value），建構子位址也放進 blob，所以**同一支 445→565 bytes 的 agent**
就能送任何一族命令，不必為每個類別重編。

新增 `p60_generic_cmd_build.py`（agent＋blob＋presets＋靜態錨點）與
`p60_generic_cmd_inject.py`（注入器，六個 preset），18 項測試全過（含 4 個 unicorn 行為模擬）。

## 1. 四個命令類別的逆向結果（本輪逐條核對 vtable）

| 類別 | vtable | ctor | size | kind | 額外欄位 |
|---|---|---|---|---|---|
| `CSanInetDomesticCmd` | 0x5039F8 | 0x4369F6 | 0x24 | 18 | +0x14 actor、+0x18 parameter、+0x1C value、+0x20 extra |
| `CSanInetPersonnelCmd` | 0x503A28 | 0x436CD3 | 0x1C | 20 | +0x14 actor、+0x18 target |
| `CSanInetPhaseEndCmd` | 0x503A40 | 0x436DDA | 0x14 | 21 | **無**（Serialize 直接用基底 0x435A44） |
| `CSanInetDiplomacyCmd` | 0x503A10 | 0x436B2E | 0x33 | 19 | +0x14..0x18 flags、+0x19/0x1D/0x21/0x25 ints、+0x29 五個 u16 卡 |

> 修正上一輪表格的錯位：`0x436D45`（會寫 +0x14/+0x18）是 **Personnel** 的 Serialize，
> 不是 PhaseEnd；PhaseEnd 的 Serialize 就是基底（body 只有 13 bytes，整筆 38 bytes）。

黃金樣本對照：
* Domestic(actor7, step, value95, extra1) = 真實 2026-10-17 擷取 54 bytes ✔
* Personnel(actor7, subtype1, target430) = 真實擷取 47 bytes ✔
* PhaseEnd = 38 bytes（`ffff0001 1300 "CSanInetPhaseEndCmd" 15000000 00000000 00000000 00`）

## 2. 實測結果（本輪，全部由風雲客戶端發送、actor 指向劉備 force 1）

| preset | 命令內容 | 回執 | 回合結算後（劉備 force1） | 孫堅 force2 |
|---|---|---|---|---|
| rice（买米） | sub3, buy=1, value=1000 | rc=1 ✔ | 米 73866 → **122441**、金 19430 → **9715** | 不變 |
| alms（施捨） | sub2, value=0, extra=4 | rc=1 ✔ | 米 122441 → **117141**、金 18371 → **15721** | 不變 |
| phaseend | kind21（風雲＋丁滿各一發） | 兩發都 rc=1 ✔ | **階段沒有提前結束**（自然倒數 64–98 秒照跑） | — |
| personnel（錄用） | sub0, actor=1, target=1（在野武將 id 1） | rc=1 ✔ | 目標武將 **仍在野**（wild 186→185 但 id1 仍 status=1）⇒ 沒被錄用 | — |

* rice / alms 的**方向與目標勢力都對**（只有 actor 那一家的米／金動），但幅度可能混到
  「玩家閒置時遊戲自己補內政」的成分（同一觀察窗內孫堅完全沒動，可作對照）。
* **phaseend 送了但沒被採用**：風雲與丁滿各送一次，主機仍等自然倒數。判定〔未定案〕——
  一種可能是「結束階段」不是走命令通道，而是走同步控制幀（控制1/2/3）＋UI 狀態機；
  合成命令只會被收進批次、在回合結算時套用。
* `personnel` 已發射（rc=1、kind20/sub0/actor=1/target=1），但**目標武將沒有加入**（仍在野）。
  〔未定案〕可能是 target 不是「武將 id」、或錄用要先滿足城池/在野所在地條件、或主機對人事另有前置檢查。
* `build`（建設）尚未發射。

## 3. 檔案

```
shots/rice-buy1000.bin        kind18 sub3 actor1 buy1 value1000 rc1 phase1
shots/alms-extra4.bin         kind18 sub2 actor1 value0 extra4 rc1 phase1
shots/phaseend-both-fy.bin    kind21 風雲（own 169174461）
shots/phaseend-both-dm.bin    kind21 丁滿（own 181830756）
shots/personnel-hire-target1.bin  kind20 sub0 actor1 target1 rc1 phase1
shots/receipts.json           四發回執解碼
tools: p60_generic_cmd_build.py / p60_generic_cmd_inject.py / test_p60_generic.py（18/18）
```

## 4. 怎麼用（下一個窗口照抄）

```bash
ZS='Z:\Users\vk\sgi-fengye-lab\shadow'
WINEPREFIX=<目標prefix> "$WINE" "$P32" "$ZS\tools\p60_generic_cmd_inject.py" --force \
  --preset rice --actor 1 --buy 1 --value 1000 --extra 0 \
  --agent-bin "$ZS\tools\agent_generic.bin" --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --flag "$ZS\p60_go.flag" --receipt "$ZS\p60_receipt.bin" --state "$ZS\p60_state.json"
touch ~/sgi-fengye-lab/shadow/p60_go.flag     # 恰一次
```

preset：`train`（--actor --troop --value --extra）、`alms`（--actor --value --extra）、
`rice`（--actor --buy --value --extra）、`build`（--actor --build-type --x --y --value --extra）、
`personnel`（--actor --subtype --target）、`phaseend`。

## 5. 未定項

1. phaseend 為何不被採用（命令通道 vs 同步控制幀）——需要看主機收到後的處理路徑。
2. personnel / build 尚未實機發射。
3. rice/alms 的精確公式被「閒置自動內政」干擾，未做純淨量測。
