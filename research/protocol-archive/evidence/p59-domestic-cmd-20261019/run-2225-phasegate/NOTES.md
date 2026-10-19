# P60 智能等待（agent 內建階段閘門）＋ 批次上限 — 2026-10-19 22:20–22:35

## 1. agent 內建「階段閘門」（本輪新增）

以前只有操作腳本在輪詢回合狀態；現在 **agent 自己會等**：blob 新增 `phase_req`（0=不限），
agent 讀 `core+0x4D8`（phase），不符就繼續睡（250ms 一輪），符合才建物件＋送出。

實機驗證（本目錄）：

```
armed at phase=4 ; 立刻 touch 觸發檔
→ agent 按住 53 秒
→ 遊戲進入 phase=1 的瞬間送出
→ 回執 rc=1 kind=18 phase_at_send=1
```

⇒ 觸發檔可以「隨時」touch，agent 會自己挑指令階段送，不會因為人手計時而漏發或發在 phase=0 被丟。
（phase=0 被丟的對照見 run-2150-build/shots/build-parade-36-41-phase0-dropped.bin）

工具：`p60_generic_cmd_inject.py --require-phase 1`；測試 `test_p60_generic` 20/20
（新增 phase gate holds / passes 兩項）。

## 2. 批次上限（同回合多發）

| 一回合條數 | 結果 |
|---|---|
| 3（火計4/落石5/陷阱6，run-2210） | 全中，traps 0→3 |
| 2（牧場/弓工坊，run-2210 工具驗證） | 全中，建築 +2 |
| **8（陷阱×8）** | **全中**：traps 3→11、八個座標一個不漏；金 17733→1733，正好 −8×2000=16000 |
| 1（extra=100 低價陷阱） | 陷阱**未生成**、金 1733→0 ⇒ 低價不是捷徑（也可能被回合開銷吃光，判不準） |

⇒ 實測下限 **一回合至少 8 條**；再往上需要更多金錢／空地，或改用零成本命令壓測。

## 3. 檔案

```
gate-receipt.bin/json    phase 閘門那一發的回執（phase_at_send=1、rc=1）
gate-state.json          注入器狀態（--require-phase 1）
agent_generic.bin        590 bytes、sha256 99dbfd06…（含閘門）
```

## 4. 未定項

1. 8 條以上的真正上限（金錢/空地/伺服器批次容量）未定。
2. 低價（extra=100）為何沒生成——是「花費不足」還是「該回合現金不足」，未分離。
