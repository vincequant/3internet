# P61 D8 精準踢人：工具完成，首測**未生效**（2026-10-20 00:45–00:55）

## 做了什麼

1. 新 agent `agent_d8.bin`（283 bytes，sha256 `2105d5b7…`）：注入 SANPK → 輪詢觸發檔 →
   組 `BE32(8)+BE32(departing_id)` → `4c80(netobj)` 取 target → `4b60(netobj,target,buf,8)` 提交 →
   寫 64 bytes 回執（magic `'D8G1'`、rc、departing、netobj、tick）。
2. 新注入器 `p61_d8_inject.py`（沿用 P60 的進程/模組定位與 CreateRemoteThread）。
3. 位址（本局實測）：koeinm 0x5a0000、netobj 0x5b2170、send 0x5a4b60、gethost 0x5a4c80。

## 兩發實測

| # | departing | 回執 | 結果 |
|---|---|---|---|
| 1 | 12345（不存在） | rc=1、netobj=0x5B2170 | 無任何影響（預期） |
| 2 | **182698283（風雲）** | rc=1 | **無效**：70 秒後主機行仍在（slot1 id 182698283）、風雲客戶端存活且繼續推進（193 年） |

## 追加實驗：幀到底有沒有出去？→ **出去了**

第三發（departing=999999，不存在的 id），用幽靈 session 的 tx 計數器前後對照：

```
before tx=80  →  發 D8（回執 rc=1）  →  after tx=81
```

⇒ `4b60` 不是只入隊，**幀真的上了線**（tx +1）。所以前一節的「可能 1（只入隊）」排除，
剩下：**主機收到但不採用**（sender 校驗或 departing id 不符條件）。

## 修正後的判定

- 通道「提交」成功（rc=1 = 已入隊），但**幀沒有造成退場**。
- 幀確實出去了（tx 80→81），主機卻沒有任何反應 ⇒ **主機端有我們沒看到的校驗/前置條件**。
  最可能是「退場只能由該成員自己的會話發起」（D8 的 departing 必須等於發送者）。
- 這意味著：**D8 精準踢人這條路很可能走不通**（除非能偽造發送者 id）。
- 仍然可用的破壞性手段：畸形建設命令（全場 AV，已實證），但那是「全場武器」。
- 下一步（若要繼續）：在 Koeinm 找 D8 上行的**組幀處**，比對「真實自退」與「我們注入」的幀差一個欄位沒有；
  或找主機 0x3fd0 之後的分支（0x407d 附近）看它拿什麼做前置。

## 檔案

```
d8-bogus-12345.bin       第一發回執
d8-target-fengyun.bin    第二發回執
tools/p61_d8_build.py    建構器（agent + blob）
tools/p61_d8_inject.py   注入器
tools/agent_d8.bin       283 bytes
```
