# SOP：藏身 ↔ 上身（2026-10-21 定稿，依 baseline-20261020-ghost-control）

> 這一頁只寫「已驗證、可照抄」的順序。任何一輪實驗失敗，先回頭比對這裡的順序，
> 不要用簡化版流程推論。

## 0. 一句話

**要「藏身（名單看不到）＋能動手（主機採用、玩家端同步）」，必須用 `arm_now.sh` 全量武裝，
不是 `sticky.sh arm` 的 5 項輕量補丁。** 兩個流程差在補丁數量與回合驅動，
輕量版會讓客戶端開局時退回「遊戲選擇」（shadow mode=0），根本沒進圖，也就沒有席位可上身。

## 0.5 2026-10-21 22:1x 修正（重要）

「先 D8 再開局」不成立：D8 之後沒有應用行，主機開局不會把我們帶進局（客戶端被打回遊戲選擇），
而且局中下指令一律被主機丟（P37/P38 已證：主機用 sender 找應用行）。
**正確認知：身份在「按開始那一刻」建立。**

```
① 進房（名單可見）
② 開局前 setforce 到目標席位（可選）
③ 房主按「開始」          ← 身份建立（cmd7 會帶到我們）
④ 開局後才 D8 摘席        ← 名單消失、身份保留（P44：換走再換回都有效）
⑤ shadow_force switch N → 在風夜視窗下指令 → 主機採用
```

## 1. 已驗證的順序（baseline tag `baseline-20261020-ghost-control`）

```
① 進房（用房間清單選房，不要在搜尋框填位址）
② 全量武裝：SEAT_SLOT=<N> JOIN_NICKNAME=<偽名> bash arm_now.sh
     - 20+ 補丁 + suppress + D8 摘席（應用行消失、DLL member 保留）
     - v2.1 回合驅動（開局安全單驅動）
③ 房主按「開始」
④ 判據：shadow mode 是否 = 3（進圖）。mode=0 = 沒進圖，本輪作廢。
⑤ 進圖後：bash shadow_force.sh switch <N>   ← 這一步才是「上身」
⑥ 下指令只走「遊戲自己的送出管線」（UI 按鈕／Hub 快速軍令 --ui-path）
     - raw 4c80+4b60（D5）→ 主機丟
     - p60 0x42a7d4 SendObject standalone → 主機丟
```

## 2. 為什麼「先 D8 再等開局」在輕量流程必失敗（2026-10-21 21:36 實測）

- 21:36:42 `sticky.sh arm`（5 補丁）→ D8 回執 `5348 4732`，複核「應用層名冊已無 xiaolight，DLL 成員保留」
- 21:52 房主開局 → 主機 `phase=live`，八席 = 丁满／彭彭 + 6 電腦；**我們不在局內**
- 我們客戶端被打回「遊戲選擇」（★看不到主机）→ 沒有席位可上身
- 判定：輕量補丁沒有裝「進圖所需」的那組修補＋驅動，D8 之後主機開局不會把我們帶進圖。

## 3. 相關事實（來自 P58 實測，不要再重驗）

1. 隱身客戶端仍收得到全部廣播（cmd7/cmd10/回合/聊天），但**不會進地圖（mode=0）**，
   除非開局時按正確順序武裝 → `run-20261019-070208`（mode=3）vs `084738`（mode=0）。
2. **已藏身狀態下，客戶端自己發幀（cmd9／D8 agent 點火）會崩**（EIP=0、ESI=0x1E0160）。
3. 主機回合批次 control5 佈局已全解；主機只吃「遊戲自己管線」送的 control4/5。
4. 每局只武裝一次（重啟影子客戶端會在大廳留痕）；切席位／開關抑制不留痕。

## 4. 下一輪照這個跑（新房）

```bash
cd ~/sgi-fengye-lab/shadow
source _env.sh
# 偽名自選；SEAT_SLOT 先用 5（空席）避免借別人的勢力被看出
SEAT_SLOT=5 JOIN_NICKNAME=xiaolight bash arm_now.sh
# 房主按開始後：
#   看 shadow mode 是否 3；是就切席位
bash shadow_force.sh switch 1        # 例：共控 slot1
```

驗收三件（缺一不算成功）：
1. 主機 `collect_84c0` +1（主機採用了我們的指令）
2. 玩家端畫面同步出現效果（例如 风雲 看到部隊）
3. 主機應用名冊仍看不到我們的偽名（藏身未破）

## 9. 2026-10-21 23:1x 收尾：今晚新增的兩個硬結論

1. **`suppress`（control1/control2 上傳抑制）會讓整桌卡在指令階段前**。
   - 證據：22:52 那局（有 suppress、無常駐驅動）→ 主機名單有 小白、phase 停在 200年春・内政，
     丁满／彭彭／小白 三家都進不了指令；把 suppress `--revert` 後客戶端恢復上傳。
   - 結論：要當「正常參與的玩家」時**不可套 suppress**；它是給「純旁聽」用的。

2. **`myforce` 兩站（0x445E98 / 0x445FE3）必須用智能守衛，不能用 nullguard 的 NULL 版**。
   - P66 已記錄：NULL 版 → 內政面板按了沒反應；跳過 → 按練兵會崩。
   - 今晚 `tools/patch_myforce_guard.py <pid>` 已在 pid 612 上 verified（eax≠0 走原比較、eax=0 安全出口），
     但**尚未在「能下單的一局」裡實機驗證**。

3. 今晚未成立：藏身（D8）＋上身（slot 0/1）＋下單 → 主機採用。
   - 22:06 的 slot0 施捨、23:0x 的出兵都沒在主機端反映。
   - 兩個可能仍未隔離：(a) 藏身＝沒有應用行 → 主機丟 sender（P37/P38）；
     (b) 那一局客戶端根本沒參與同步（suppress／無驅動），指令從未離開本機。

## 10. 明天最省時的一條路

```
① 房間清單進房（名單可見）→ 確認主機名單有自己
② 只裝：nullguard + start-nulls（跳 myforce）+ patch_myforce_guard + 常駐驅動
   **不裝 suppress、不裝 panel-skip、不裝 element-fallback**（今晚證明它們傷同步／UI）
③ 房主按開始 → 立刻按一筆施捨 → 讀主機金／collect
④ 成功後才 D8，再按一次同一指令 → 判「藏身後是否仍被採用」
```

## 11. 2026-10-22 01:1x 三窗口現況（交接）

### 已做好的
- `~/sgi-fengye-lab/shadow/one_click_three.sh`：新的三窗口一鍵（丁满建房 → 風夜進房 → 補丁 → 可選 D8）。
- 每個 prefix 的 **LoaderUdpPort 已分開**（dingman 4577 / sikarugir10 4578 / fengye-shadow 4579，備份 .bak-port）。
- 每個帳號的啟動設定：`~/sgi-direct-connect/machine-dingman.json`、`machine-fengyun.json`＋`run3.sh`（原本 machine.json 全部指到 shadow prefix，是三窗口失敗的元兇）。

### 還沒解決的兩個卡點
1. **帳號 already logged in**：`丁满` 協議登入回「用户已经登录…请本人在已登录端退出，或在大厅勾选强制登录」。
   → 需要先讓該帳號在大廳那邊退出（或改用強制登入），否則起不來。
2. **視窗探測對不上**：launcher 回 `ready / hold_started`、`lsof` 也看到 prefix-dingman-local 的 SANPK，
   但 `win_probe.py` 在那個 prefix 找不到「游戏选择」→ `game_browser.py create` 回 `browser not found`。
   → 需要在 dingman prefix 下重新確認 `win_probe` 的視窗列舉（可能要用該 prefix 的 python32 路徑＋不同 API）。

### 另外
- 風夜那台有 **重複 SANPK（自動重啟）**：`sanpk_relaunch` 類補丁會在 kill 後再拉一台，測試前要先清。

## 12. 2026-10-22 07:5x 啟動器硬化（三窗口）

### 已加（launch_shadow_local.py，備份 .bak-20261022）
- `_kill_strays()`：啟動前清掉本 prefix 殘留 SANPK（實測 `strays_killed: ["23917"]`）。
- `_browser_ready()`：啟動後輪詢「游戏选择」視窗（標題＝游戏选择 且 enabled），
  150 秒內沒出現就 `window_missing` 並回 ok=false（不再只看進程存在）。

### 仍然存在的真因（今晚查到的）
1. 助手自己會再拉一台：日誌 `{"helper": {"event": "sanpk_relaunched", ...}}`
   → 一個 helper 產生兩個 SANPK，補丁工具因此拒絕（`need exactly 1`）。
2. 客戶端最後停在**大廳**（視窗 `三国志六网际网络增强版`），不是「游戏选择」
   → 清單永遠是空的（`items: []` / `browser not found`）。
   ⇒ 不是房間不存在，是這台沒有走到「游戏选择」。

### 下一步（明天）
- helper 的 relaunch 條件要加「已有 SANPK 就不拉」。
- 客戶端停在大廳時，要自動點「進入遊戲」把它帶到「游戏选择」，
  或在啟動參數直接把 hall 步驟跳過。
