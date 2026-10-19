# P60 批次發射（一回合多發）＋ 陷阱三型（4/5/6）**同時完成** — run-2210

日期：2026-10-19 22:05–22:15 ｜ 同一局（190 年）｜ 發送端：風雲客戶端｜ actor=劉備 force 1｜城 平原 city 5

## 0. 結論（兩件事一起做到）

1. **一回合多發成立**：三個 agent 先後注入、三個觸發檔「同時 touch」，
   三條命令**都在同一個 phase=1 回合內送出**（三份回執的 phase 都是 1），回合結算後遊戲裡一次長出三個物件。
2. **陷阱三型（4 火計／5 落石／6 陷阱）全部成立**：`traps` 容器 0 → **3**，
   座標正是指定的三格、歸屬劉備（owner=1）。

## 1. 實測

命令（同一回合、三個 agent 同時放行）：

| # | parameter | 座標 | city | extra | 回執 |
|---|---|---|---|---|---|
| 1 | 4 火計 | (34,39) | 5 | 2000 | rc=1、phase=1 |
| 2 | 5 落石 | (36,39) | 5 | 2000 | rc=1、phase=1 |
| 3 | 6 陷阱 | (36,41) | 5 | 2000 | rc=1、phase=1 |

回合結算後（`_p60_traps.py` 唯讀讀回）：

```
traps = [ {type:trap, xy:[34,39], owner:1},
          {type:trap, xy:[36,41], owner:1},
          {type:trap, xy:[36,39], owner:1} ]     ← 正好三格、正好我們的座標
production_buildings 仍為 53（沒有誤傷既有建築）
```

⇒ 建設的 parameter 4/5/6 與 7/8/9 **九種全部實測通過**：
- 4 火計、5 落石、6 陷阱 → 進 `traps` 容器
- 7 練兵所、8 牧場、9 弓工坊 → 進 `production_buildings` 容器（前一輪 run-2150）

## 2. 批次做法（可重用）

`p60_multi_build.sh`：

```bash
bash ~/sgi-fengye-lab/shadow/p60_multi_build.sh 1 "$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10" \
     4:34:39:2000 5:36:39:2000 6:36:41:2000
```

流程：對每個 `type:x:y:extra` 注入一個一次性 agent（各用自己的 flag/receipt）→
等到穩定的 phase=1 → **一次 touch 所有 flag** → agent 在 250ms 輪詢內幾乎同時送出 →
收齊回執。每個 agent 仍然「恰一次」，失敗不重試。

> 為什麼不用「一支 agent 連發 N 條」：現行做法把「單發」紀律留在 agent 內，
> 批次只是把 N 個單發排在同一個回合窗口，行為可預測、回執一發一份，出錯容易定位。

## 3. 檔案

```
shots/trap-fire-34-39.bin     type 4 火計 回執
shots/trap-rock-36-39.bin     type 5 落石 回執（檔名 p60_mi_rock.bin 存檔時改名 rock）
shots/trap-trap-36-41.bin     type 6 陷阱 回執
shots/receipts.json           三發解碼
traps-after.json              結算後 traps 容器（三筆，座標/歸屬正確）
tools: p60_multi_build.sh（批次）、_p60_traps.py（唯讀驗收）
```

## 4. 未定項

1. 三發同時送出時**扣款**沒有乾淨的前後對照（該回合也有收入），只確認物件生成；
   單發時（run-2150）扣款是精確的 −2000。
2. 同格重複建設、敵方城池上建設、超過城池附屬格範圍的座標，都還沒測。
3 . 一次最多能塞幾條命令進同一批次（伺服器/批次上限）未測。

## 5. 批次工具驗證（22:18–22:22）

用**可重用的** `p60_multi_build.sh`（不是臨時腳本）再跑一批兩發：

```
bash p60_multi_build.sh 1 <prefix-sikarugir10> 8:36:42:2000 9:38:41:2000
→ armed #1 type=8 @(36,42) / armed #2 type=9 @(38,41)
→ phase 1 -> firing 2 commands at once
→ #1 rc=1 type=8 xy=(36,42) phase=1 ; #2 rc=1 type=9 xy=(38,41) phase=1 ; receipts 2/2
```

回合結算後 force1 的建築清單：

```
parade_ground (33,37)   ← 原本就有
horse_farm    (35,39)   ← run-2150 第1發
bow_studio    (35,41)   ← run-2150 第2發
parade_ground (34,41)   ← run-2150 第3發
horse_farm    (36,42)   ← 本批 #1
bow_studio    (38,41)   ← 本批 #2
```

⇒ 批次工具端到端可用：一批命令在同一個 phase=1 內全部落地、每發一份回執。
