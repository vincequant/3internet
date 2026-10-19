# P59 實機：免界面合成命令（kind 18 訓練）**成立** — run-2054

日期：2026-10-19 20:52–21:05 ｜ 房名 SGZWLB ｜ 劇本「189年 董卓之野心(中原)」
參與：丁滿（host、slot0、劉備 force1）／風雲（slot1、孫堅 force2）／風夜（藏身，開局前已退出，見 §5）

## 0. 結論（一句話）

**用注入的一次性 agent，在「不切視角、不點界面」的情況下，以遊戲自己的建構子造出
`CSanInetDomesticCmd`，交給遊戲自己的 `0x42A7D4` 送出 → 主機在回合結算時真的套用，
目標勢力訓練度按命令上升、金錢按命令扣除，兩台客戶端數值一致。**
四發實測（價值 95／200／100(騎)／300）全部 `rc=1`、對局閘門未被動到、回合照常推進。

## 1. 四發數據

| # | 時間 | 發送端 | actor | parameter | value | 送出時 phase | 訓練度 前→後 | 金 前→後 |
|---|---|---|---|---|---|---|---|---|
| 1 | 20:54 | **風雲**（非劉備的擁有者） | 1 劉備 | 0 步 | 95 | 1 | 步 **70 → 108（+38）** | 12270 → 11270（−1000） |
| 2 | 20:58 | 風雲 | 1 | 0 步 | 200 | 1 | 步 93 → **173（+80）** | 11270 → 10270（−1000） |
| 3 | 21:00 | 風雲 | 1 | 1 騎 | 100 | 1 | 騎 70 → **100（+30）** | 10270 → 9270（−1000） |
| 4 | 21:03 | 風雲 | 1 | 0 步 | 300 | 4 | 步 173 → **293（+120）** | 9270 → 7770（−1500） |

- 另一個勢力（孫堅 force2）在四發中**完全沒被動到**（30/0/101 → 只有它自己的自動徵兵造成 88），
  ⇒ `actor` 真的是「指定勢力」。
- 三發步兵：95→+38、200→+80、300→+120 ⇒ **訓練度增量 = value × 0.4（整數）**，三點全中。
- 花費：95/100/200 都是 −1000，300 是 −1500 ⇒ **花費 = max(1000, value × 5)**，四點全中。
- 騎兵那一發只 +30（預期 40）⇒ 该回合同時發生了自動徵兵（騎兵未變、但訓練度可能被稀釋），
  或兵種係數不同 —— **待補一發乾淨樣本**（列入未定項）。
- 兩台客戶端在所有終值上**逐欄位一致**（`lords-final-*.json`）。
- 回合：phase 1 →（約 30–60 秒倒數自動結束）→ 3 → 4 → 下一回合，`tick 2→3→2`、`f6bc 1→0`，
  沒有卡死、沒有崩潰。**指令階段有倒數，會自動結束回合**（本次沒有點任何「結束」按鈕）。

## 2. 逐發回執（48 bytes，`shots/`、`receipt.*`）

```
magic 'S5RC' | rc=1 | core=0x42E2B0A | actor | parameter | value | extra | tick | gate_before | gate_after | phase | own
shot1 (20:54)  actor1 param0 value95  tick450110539 gate 1/1 phase1 own175968945  → receipt.bin
shot2 (20:58)  actor1 param0 value200 tick450340459 gate 1/1 phase1
shot3 (21:00)  actor1 param1 value100 tick450454578 gate 1/1 phase1  → shots/shot3-receipt.bin
shot4 (21:03)  actor1 param0 value300 tick450577818 gate 1/1 phase4  → shots/shot4-receipt.bin
```

`gate_before == gate_after == 1` 證明 agent 走的是 `0x42A7D4`、**沒有**經過 `0x446482`
（界面路徑會把閘門先歸零再歸一）。

## 3. 這台「發送端」是誰

本次發送端＝**風雲**（prefix-sikarugir10，own=175968945）。它送的是**劉備（force 1）**的命令，
而劉備是丁滿的勢力 ⇒ 這一發本身就是「**A 客戶端替 B 勢力下命令**」，主機照單全收。
（原計畫要用藏身的風夜送；風夜在開局前就退出，見 §5。）

## 4. 開局流程（本次由 agent 全自動點完，之後可重用）

1. `one_click_test.sh` → 三開＋建房／進房＋補丁＋D8 摘席＋slot=5（本次 20:41 完成）。
2. 房主：`ui_click.py 剧本选择` → 開「剧本选择」對話框（清單是 game 自繪的 owner-draw 清單）。
   **關鍵**：清單項沒有一般 LVM 幾何（`LVM_GETITEMRECT` 全 0、`LVM_HITTEST` 全 −1），
   但**對清單窗口直接 PostMessage 滑鼠點擊就會選中並自動關閉對話框**
   （y=24 命中第一項）。本次選到「189年 董卓之野心(中原)」。
   → 房間左上角 Static 1009 由空字串變成劇本名，即為成功判據。
3. `ui_click.py 随机顺序`（隨機分配君主順序）。
4. 每個玩家**在自己的客戶端**點自己那一列的「君主选择」按鈕（控制項 id 1013+row）：
   丁滿→劉備、風雲→孫堅；在彈出的君主清單裡點一位（座標 120,80 = 劉備；300,120 = 孫堅），
   再按「确定」。
5. 房主 `ui_click.py 开始游戏` → 進入地圖（出現「小地图」視窗即成功）。

> 沒有這一步的劇本選擇，按開始只會得到「请先选择剧本。」；只按「开始游戏」不選君主會得到
> 「还有玩家尚未决定担任君主。」。兩者都用 `_p59_dlg_kids.py` 讀訊息框文字確認。

## 5. 風夜（藏身幽靈）本次未能參與

- 20:41 一鍵完成時三台都在、幽靈已藏身（主機名冊 2 行）、slotkeep(5) 在跑。
- **約 20:44 幽靈客戶端整條鏈消失**（helper pid 18290 與 SANPK pid 1804 都不在；
  情報台 recorder 心跳同時停在 20:44）。時間點在我第一次按「开始游戏」（得到「请先选择剧本」）之後。
- 推測（未證）：slotkeep 每 250ms 往 core+0x6c0 寫 5，房間→開局切換時 core 重新配置，
  寫到舊位址 ⇒ 客戶端崩潰；或 D8 摘席＋房間狀態變動造成的原生崩潰（P42 有 8.5 分鐘後崩的先例）。
- 因此本次的「發送端」退而用風雲（真人客戶端）。**「藏身幽靈發命令」仍待一次新局實測**
  （流程已可全自動，見 §4；下次一鍵後先確認幽靈存活再開局）。

## 6. 重現指令（本次每一發都是這樣打的）

```bash
cd ~/sgi-fengye-lab/shadow && source ./_env.sh
ZS='Z:\Users\vk\sgi-fengye-lab\shadow'
FENGYUN_PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10"
rm -f p59_go.flag p59_receipt.bin
WINEPREFIX="$FENGYUN_PREFIX" WINEDEBUG=-all PYTHONIOENCODING=utf-8 \
 DWLD="$HOME/Library/Application Support/SGI-Wine/dependency-lib" \
 "$WINE" "$P32" "$ZS\tools\p59_domestic_inject.py" --force \
  --agent-bin "$ZS\tools\agent_domestic.bin" --koeinm 'C:\sgi\run-3.5\3I\Koeinm.dll' \
  --actor 1 --parameter 0 --value 300 --extra 0 \
  --flag "$ZS\p59_go.flag" --receipt "$ZS\p59_receipt.bin" --state "$ZS\p59_state.json"
touch p59_go.flag          # 恰一次
```

（實際腳本用 `tools/p59_domestic_fire.sh` 亦可，但其 prefix 需改成風雲／風夜；
本次因為幽靈不在，手動指定了 `FENGYUN_PREFIX`。）

## 7. 檔案

```
lords-before-2052.json      發射前讀值（70/70/0、30/0/101）
lords-after-host.json       第一發回合結算後（步 108、金 11270）
lords-after-fengyun.json    同上（另一台，逐欄位一致）
lords-final-host.json       四發後終值（步 293、騎 100、金 7770）
lords-final-fengyun.json    同上（另一台）
receipt.bin/.hex/.json      第一發回執
shots/shot3-receipt.bin     第三發（騎兵）回執
shots/shot4-receipt.bin     第四發（value 300）回執
state.json                  注入器狀態（code/blob 位址、thread id）
```

## 8. 未定項

1. 騎兵那一發 +30（預期 40）—— 需要一發「該回合沒有自動徵兵」的乾淨樣本才能定係數。
2. `extra` 仍未證語義（四發都填 0）。
3. 藏身幽靈當發送端：待新局（流程已自動化）。
4. value 上限：300 仍正常（+120）；UI 內部 clamp 300，伺服器是否接受更大值未知。
