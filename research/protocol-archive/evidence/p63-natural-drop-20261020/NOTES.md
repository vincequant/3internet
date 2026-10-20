# P63 自然斷線：進程內 ExitProcess → 主機出現標準「恢復連線中→無法重新連線→退出」三行

**時間**：2026-10-20 08:17:52（注入）→ 08:18:26（主機名冊摘除）
**場景**：本機三開自測房 SGZWLB（丁滿房主、風雲、風夜已藏身），開局前。

## 做法

- 新工具 `p63_drop_inject.py`（Wine py32，跑在目標 prefix）：Toolhelp 找 SANPK，
  psapi 取 kernel32 base，組 10 bytes shellcode `push 0; mov eax, ExitProcess; call eax`，
  VirtualAllocEx + CreateRemoteThread。**在進程內自殺**（不是從 shell kill，避免帶崩 wineserver）。
- 目標＝風雲（prefix-sikarugir10，wine pid 816，kernel32 0x7beb0000，ExitProcess 0x7bebe9bc）。
- 觀察：主機（丁滿）L 表＋RichEdit 訊息區，每 5 秒一筆（`host-watch.txt`）。

## 結果（主機視角，逐字）

```
08:18:20  rows=[(0,丁满),(1,风云)]
08:18:26  rows=[(0,丁满)]            ← 風雲的列被摘除
          訊息：
            风云正恢复连线中...
            风云无法重新连线。
            风云从游戏中退出了。
```

- 從注入到名冊摘除約 **34 秒**，三行文字順序與真實掉線一致（截圖 `host-window.png`）。
- 受害端（風雲）視窗直接消失（進程死亡）；其他玩家看到的是標準掉線流程，沒有任何人為痕跡。
- 對照：D8 踢人是「靜默除名」（名冊仍在、單向聊天、無斷線對話框，見 p62 NOTES），
  這次是**真斷線**——socket 隨進程死亡關閉，主機走重連→失敗→退出。

## 判定

- 「自然斷線」第一版達成：**外觀與真實網路掉線相同**（三行、約 30 秒、名冊摘除）。
- 代價：目標客戶端直接消失（需重開）。若要更溫和（客戶端留著、顯示自己的「恢復連線中」），
  下一步是只關 Koeinm↔loader 的 socket（需找 socket handle），或暫時遮斷其網路。

## 檔案

- `host-watch.txt`：主機列＋訊息逐 5 秒記錄
- `host-window.png`：主機視窗截圖（三行清楚可見）
- 工具：`research/client/protocol-lab/p63_drop_inject.py`（lab `tools/p63_drop_inject.py`）
