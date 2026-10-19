# P62 D8 狀態對照：在席踢人 / 藏身踢人 / 隱身退出（2026-10-20 07:44–07:52）

環境：本機三開自測局（丁滿房主 `prefix-dingman-local`、風雲 `prefix-sikarugir10`、
風夜影子 `prefix-fengye-shadow`），房名 **SGZWLB**，全部在**開局前**（native `netobj+0x84A8 == 1`）。
D8 由風夜影子客戶端進程內的 P61 agent 發出（`4c80` 取 host → `4b60(netobj, host, body, 8)`，
body = `BE32(8)+BE32(departing)`），每發一次、不重試。

---

## E3 在席踢風雲 → **成功**

- netobj（風夜，在席，名冊 3 人）：`is_host=0`、`rows_n=3`、
  `row_ids=[168484240(自己), 178390280(丁滿), 168299312(風雲)]`、`4c80 → 178390280`（主機 id）。
- 回執：`D8G1 rc=1 departing=0x0A080B30(168299312) netobj=0x5B2170`。
- 主機 L 表：
  - before：`[(0,178390280,丁满),(1,168299312,风云),(2,168484240,待秋至)]`
  - after ：`[(0,178390280,丁满),(2,168484240,待秋至)]` ← 風雲 slot1 被清成 `id=0/name=''`
- 主機日誌新增：`风云从游戏中退出了。`

## E1 自我 D8 藏身（既有流程）→ 成功，但**留一行字**

- `hide_now.sh`（P51 agent，departing=自己）→ 主機 L 表 row 消失（名冊 3→2）。
- 主機日誌新增：`待秋至从游戏中退出了。` ← **D8 自退一定有這一行**，不是無痕。

## E4 藏身狀態下踢風雲 → **成功**（本輪關鍵）

- 先讓風雲離房再重進（`取消→是→游戏选择→加入 SGZWLB→确定`），主機 L 表回到
  `[(0,丁满),(1,风云)]`，幽靈仍在藏身（名冊只有 2 行）。
- 幽靈 netobj：`is_host=0`、`state_84a8=1`、`rows_n=3`（**自己的 DLL 成員表**仍有 3 人：
  自己/丁滿/風雲）、`4c80 → 178390280`。
- 回執：`D8G1 rc=1 departing=168299312`。
- 主機 L 表 after：`[(0,178390280,丁满)]` ← 風雲再次被摘除。
- 主機日誌新增：`风云从游戏中退出了。`
- ⇒ **「藏身（非在席）發送者」的 D8 主機照收**；P61 的「主機不信非在席發送者」假設不成立。

## E5 藏身狀態下正常關閉幽靈客戶端（WM_CLOSE）→ **零文字**

- 對影子客戶端 top window 送 `WM_CLOSE`（`p62_close_window.py`），SANPK 正常退出。
- 主機日誌**沒有新增任何一行**（前後 tail 完全相同）；主機 L 表不變（丁滿+風雲）。
- ⇒ **隱身退出＝藏身後走真實離場（不發 D8）**；D8 自退反而會多一行。

## 對 P61 負結果的解釋（更新）

- P61 三發都在 **局已開始（193 年）** 之後；E3/E4 證明「在席」與「藏身」在**開局前**都能踢。
- 剩下唯一未測的變量＝**局中**（host 的 D8 走 `3fd0` 的 state 0/3/4 佇列，等 `36e0` 回合結束處理）。
  P61 的失敗最可能是「局中 D8 的處理時機/前置」而不是通道、ABI 或藏身。
- 下一發：局中踢人（E6），需先開局。

## 檔案

```
seated-kick-fengyun/{rows-before,rows-after}.json  netobj.json  inject.txt  receipt.hex  hosttext-*.txt
hidden-kick-fengyun/{同上}
```
（`rows-*.json` 是主機 L 表原始讀數；`hosttext-*.txt` 是主機 RichEdit 訊息區尾部。）

## 工具

- `research/client/protocol-lab/p62_netobj_probe.py`：唯讀讀 netobj 欄位＋4c80 目標。
- `research/client/protocol-lab/p62_d8_shot.sh`：一發 D8＋前後證據。
- `research/client/protocol-lab/p62_close_window.py`：WM_CLOSE 關窗（隱身退出用）。
- `~/sgi-fengye-lab/shadow/one_click_test.sh --no-hide`：停在坐席狀態（預設行為未變）。

## E6（待跑）局中踢人

- 需要：丁滿先選劇本＋兩位玩家選君主 → 按開始 → 局中對風雲發一發 D8。
- 判讀：主機 L 表是否**立刻**少一行（state 1/2 立即分支）或等回合結束（state 0/3/4 → `36e0`）。
- 這一發同時回答「P61 為何在 193 年那局無效」：若局中也立即生效，P61 的失敗就是它自己那晚的客戶端狀態，
  不是協定限制。

## 本輪順手修好的 lab 腳本（都在 `~/sgi-fengye-lab/shadow/`，原檔備份）

| 檔 | 問題 | 修法 |
|---|---|---|
| `VKShadowLauncher.app/Contents/MacOS/run` | `cd ~/sgi-protocol-lab-20260915/shadow`（本機不存在）→ app 直接退出，`arm_now.sh` 永遠 JOIN TIMEOUT | 找不到舊路徑時 fallback 到 `~/sgi-fengye-lab/shadow` |
| `launch_shadow.py` / `launch_shadow_local.py` | `HUB=~/Applications/SGI-Hub`（不存在，缺 `sgi_room_monitor`）→ `ModuleNotFoundError` | 依序找 `~/sgi-direct-connect/hub`、`~/Applications/SGI-Hub` |
| 同上 | 線路寫死 `多线3（备用）` | `LINE_TITLE` 改讀 `line.txt` 第一行（沒有則 `SHADOW_LINE`，再沒有才用預設）；**預設行為不變**。轉線路 2：`echo '多线2（主线）' > ~/sgi-fengye-lab/shadow/line.txt` |
| `arm_now.sh` | `verify_patches nullguard 22`，現行注入器只有 21 站（第 22 站 0x195AF 已於 10-19 撤回）→ 每次 arm 都 abort | 改成 21 |
| `one_click_test.sh` | 沒有「停在坐席」模式 | 新增 `--no-hide`（已鏡像回 repo） |
