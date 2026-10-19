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

## 判定

- 通道「提交」成功（rc=1 = 已入隊），但**幀沒有造成退場**。
- 三種可能（未分離）：
  1. `4b60` 只是入隊，真正發射要等同步/批次 flush（P34 的 probe 是完整會話進程，可能自帶 flush 路徑）；
  2. 主機端其實有 sender 校驗（靜態讀到的 0x3fd0 沒看到，但可能在更上層）；
  3. D8 body 還需要額外封裝（信封 layer）。
- 下一步：抓包確認「有沒有幀真的出去」——這是最快分離 1/2 的方法。

## 檔案

```
d8-bogus-12345.bin       第一發回執
d8-target-fengyun.bin    第二發回執
tools/p61_d8_build.py    建構器（agent + blob）
tools/p61_d8_inject.py   注入器
tools/agent_d8.bin       283 bytes
```
