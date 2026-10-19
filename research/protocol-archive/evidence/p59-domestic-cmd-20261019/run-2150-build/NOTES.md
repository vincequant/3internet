# P60 建設（kind 18 subtype 4）：**兩種建築實測成功** — run-2150

日期：2026-10-19 21:45–21:55 ｜ 同一局（190 年）｜ 發送端：風雲客戶端（在同步名單）｜ actor=劉備 force 1

## 0. 結論

**建設指令完全成立，而且參數語義全部對上了：**

```
kind 18 / subtype 4
  parameter (+0x18) = 建築類型   7 練兵所 / 8 牧場 / 9 弓工坊（4 火計 / 5 落石 / 6 陷阱）
  operand   (+0x0C) = 世界座標    x | (y << 16)
  value     (+0x1C) = 城池 id     （設施掛在這座城）
  extra     (+0x20) = 花費金      （結算時一對一扣掉）
```

兩發都在回合結算後**真的長出新建築物件**（遊戲自己的 `production_buildings` 容器 50 → 51 → 52），
歸屬、掛城、座標、耐久全部正確，金錢各扣 2000（= extra）。

## 1. 實測數據

| # | 命令 | 回合結算前 | 回合結算後 |
|---|---|---|---|
| 1 | 牧場（8）@ (35,39)，city 5，extra 2000 | 劉備建築：練兵所 (33,37)；金 15721 | **新增 `horse_farm` @ (35,39) linked=5、amount 15000、def 100/450**；建築總數 50→51；**金 15721→13721（−2000）** |
| 2 | 弓工坊（9）@ (35,41)，city 5，extra 2000 | 金 23047 | **新增 `bow_studio` @ (35,41) linked=5、amount 15000、def 100/450**；建築總數 51→52；**金 23047→21047（−2000）** |
| 3 | 練兵所（7）@ (34,41)，city 5，extra 2000 | 金 21047 | **新增 `parade_ground` @ (34,41) linked=5、def 100/450**；建築總數 52→53；**金 21047→19047（−2000）** |
| 4（對照） | 練兵所（7）@ (36,41)，city 5，extra 2000，**phase=0 時送出** | — | **沒有新增、金沒扣** ⇒ 非指令階段送出的命令會被丟棄 |

* 兩發回執都 `rc=1`、`gate 1/1`、`phase=1`、`kind=18 sub=4`，`vt=0x5039F8`（DomesticCmd）。
* 目標城池是劉備的**平原（city_id 5，世界座標 35,40）**；選址 (35,39)/(35,41) 是城旁 1 格的空地
  （用 `terrain_grid` 挑 terrain=2 且未被佔用的格）。
* 孫堅（force 2）全程沒有任何新增建築、金錢也沒動。

## 2. 逆向對照（本次用實測回填）

| 欄位 | 物件 offset | 本次實測值 | 說明 |
|---|---|---|---|
| kind | +0x04 | 18 | 內政 |
| subtype | +0x08 | 4 | 建設 |
| operand | +0x0C | 0x270023 / 0x290023 | x=35, y=39 / y=41（低16=x、高16=y）|
| actor | +0x14 | 1 | 劉備 |
| parameter | +0x18 | 8 / 9 | 牧場 / 弓工坊 |
| value | +0x1C | 5 | 平原 city_id |
| extra | +0x20 | 2000 | 花費金，結算時扣除 |

線路（第一發）：
```
ffff010013004353616e496e6574446f6d6573746963436d64  ← 類別標頭（54 bytes 整筆）
12000000 04000000 23002700 00                        ← kind18 sub4 operand(x35,y39) 空字串
01000000 08000000 05000000 d0070000                  ← actor1 type8 city5 cost2000
```
（原始 expected_wire_hex：`ffff010013004353616e496e6574446f6d6573746963436d6412000000040000002300270000010000000800000005000000d0070000`）

## 3. 檔案

```
shots/build-horsefarm-35-39.bin   回執（rc=1、kind18/sub4、op=0x270023、actor1/type8/city5/extra2000）
shots/build-bowstudio-35-41.bin   回執（rc=1、kind18/sub4、op=0x290023、actor1/type9/city5/extra2000）
shots/receipts.json               兩發解碼
buildings-after.json              第二發後 force1 的三座建築
buildings-final.json              第三發後 force1 的四座建築（練兵所×2＋牧場＋弓工坊）
shots/build-parade-34-41.bin      第三發（type 7）回執
shots/build-parade-36-41-phase0-dropped.bin  對照：phase=0 送出、rc=1 但沒有生效
lords-after.json                  結算後金錢
```

## 4. 重現指令

```bash
ZS='Z:\Users\vk\sgi-fengye-lab\shadow'
WINEPREFIX=<目標prefix> "$WINE" "$P32" "$ZS\tools\p60_generic_cmd_inject.py" --force \
  --preset build --actor 1 --build-type 8 --x 35 --y 39 --value 5 --extra 2000 \
  --agent-bin "$ZS\tools\agent_generic.bin" --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --flag "$ZS\p60_go_build.flag" --receipt "$ZS\p60_receipt_build.bin" --state "$ZS\p60_state_build.json"
touch ~/sgi-fengye-lab/shadow/p60_go_build.flag
```

選址小抄：`tools/_p60_pick_cell.py <wine_pid> <city_x> <city_y> <force>` 會回傳城旁
terrain=2、未被佔用的候選格；`tools/_p60_build_view.py <pid> <force>` 讀該勢力的城與建築（驗收用）。

## 5. 未定項

1. `parameter` 4/5/6（火計/落石/陷阱）尚未實測；陷阱那筆真實樣本 value=25、extra=2000 的語義
   應該與本次相同（value=city_id、extra=金），但未實地驗證。
4. **送出時機很重要**：第 4 發在 phase=0（非指令階段）送出，rc=1 但主機不套用；三發成功的都在 phase=1。
   這與練兵/米交易/施捨的觀察一致。
2. `amount`（新牧場 15000、舊練兵所 2600）是遊戲自己算的，與 extra 無關；用途未查。
3. 同格重複建設、敵城上建設等邊界未測。
