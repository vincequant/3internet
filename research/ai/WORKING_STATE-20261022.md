# 可用狀態快照（2026-10-22 09:38）— 使用者確認「控制是可以的」

## 現場
```
時間      09:38
客戶端    SANPK 68067（prefix-fengye-shadow）
連線      UDP 4577 / 8077 都在（wineserve 94785）
房間      line3 host 丁满 10.109.55.49（遠端主機）3/8
席位      slot_now = 0
slot_forces {0: 21, 1: 17}
D8 回執   09:37:07 · 5348 4732 · 應用層名冊已無 xiaolight、DLL 成員保留
補丁      nullguard／開局守衛（跳 myforce）＋ myforce 智能守衛（pid 860）
          panel-skip / element-fallback 已還原、suppress 已還原
去霧      未安裝（保留開局迷霧）
```

## 與流程的對應（可重現）
1. 上線：`JOIN_NICKNAME=xiaolight bash sticky/sticky.sh protocol-up`
2. 進房：`bash join_now.sh`（清單選房，先關模態）
3. 武裝：`SEAT=0 bash patch_now.sh`（補丁→還原→守衛→綁 slot0）
4. 摘席：`bash sticky/sticky.sh arm`（D8，回執 5348 4732）
5. Hub：一鍵登入＝1–4 全包；一鍵武裝＝3–4；去霧另按

## 教訓（今天）
- D8 **之後**只要 UDP 還在，指令是通的（本局即為證據）。
- 之前兩局「指令沒反應」時，UDP 已經消失＝連線掉了，不是 D8 本身的問題。
  判準：`lsof -nP -p <pid> -iUDP` 有沒有 8077/4577。
