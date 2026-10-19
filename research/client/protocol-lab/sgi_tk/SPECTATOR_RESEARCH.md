# 旁观/隐形进房研究结论文档

日期：2026-10-09（只读梳理，本次未进他人房、未开监控常驻、未 ingest）  
问题：小号能否经协议进入别人建的对战，**不占会员席位**，并在别人开局后**持续搜集局内同步数据**。

对照证据：

- `evidence/hidden-player-check-20261007/`（含 `RESULT.md`）
- `evidence/alternate-observer-paths-20261007/`（`nonjoining*` / `raw_nonjoining_search`）
- `evidence/ip-state-read-20261007/`（含 `RESULT.md`、`SPECTATOR_SCOPE.md`）
- Hub：`SGI-Hub-CrossOver-M4-0.2/room_monitor/sgi_room_monitor/{protocol_session,sanpk_takeover,win32_startserver,main_lobby}.py`
- 相关：`sgi_tk/PROTOCOL_PRESENCE.md`（大厅存在感，勿与局内席位混谈）

---

## 可执行结论（一句话）

**部分能。**

| 目标 | 结论 | 条件 |
| --- | --- | --- |
| 不 OpenSession、只 SearchSession / 定向 UDP 发现房间 | **能**（不占 SANPK 席、不进 Koeinm members） | 需已有合法中继/VPN 身份；开局后搜房常被关（`+0x8414=0`） |
| OpenSession/Join 进别人对战 | **会占席** | 等待阶段一加入即写入八人玩家记录 + Koeinm 成员表；开局后拒绝新加入 |
| 不占席仍收开局后局内同步 | **未证实；标准 SendData 路径下像不能** | 同步只发给 `+0x43b8` 成员槽；搜房/查询者不在该表 |
| 不露平台「房间用户」但仍能 StartServer 搜房 | **部分能（自有监控）** | `0x200b` 拿 grant → 立刻 `0x2002` 离大厅（`leave_hall_after_grant`）；**不等于**隐形进别人局 |

**对用户原问的直接回答：以现有证据，小号不能「协议进别人局 + 不占会员席 + 开局后持续收同步」。能稳定做的是搜房/列表监控（不 join）；要局内数据应走己方/授权房主 Hub 采集，而非隐形旁观。**

---

## 1. 三层名单（必须分开）

| 层 | 载体 | 看见什么 | 主要触发 | 与「会员席位」关系 |
| --- | --- | --- | --- | --- |
| **A. 平台大厅「房间用户」** | SANGUO TCP（约 `25001`），`0x200b` ENTER / `0x2002` LOGOUT | 页签「房间用户(N)」、进出聊天 | 进线拿 grant | **不是** SANPK 八人席；人数可与局内侧无关 |
| **B. 对战房间 SearchSession 列表** | Koeinm `_NetMsg_SearchSession` / UDP 发现 | 房间名、房主、人数等摘要 | 主机 `EnableJoin` 门控（`+0x8414`） | **不加入**则不进 C 层；开局后常无回应 |
| **C. 局内成员席位** | Koeinm members（`+0x43b8` 槽、每项 `0x164`）+ SANPK 八人 `network_id` | 玩家名/君主席、`connected_member_count` | `_NetMsg_OpenSession` 等真正会话加入 | **这才是「会员席位 / maximum」占用**；标准 `SendData` 只发给此表 |

Hub 对照：`protocol_session` 管 A 层登录进线；`win32_startserver` / `sanpk_takeover` 用 grant `StartServer` 拉 SANPK 做搜房（B），**默认不应 OpenSession 进别人 C 层**（见 `PROTOCOL_PRESENCE.md` 的 `opensession_join=false`）。

---

## 2. 已有证据梳理

### 2.1 hidden-player（OpenSession 网络加入）

场景：用户自有测试房 `SGZWLB` / 房主 `kwankwan`（host id `176202538`，地址 `10.128.163.42:7777`）；用本机主号传输身份做 `_NetMsg_OpenSession`（**非**隐形小号成功案例）。

| 时刻 | 平台「房间用户」 | Koeinm members | SANPK 席位 `network_id` |
| --- | --- | --- | --- |
| 加入前 | （当时读数见各 jsonl；与 C 层独立） | count=1：仅房主 | slot0=房主，slot1…7=0（`host-slots-baseline.txt`） |
| 加入中（35s/90s 保持连接） | 同窗口读到「房间用户(4)」 | count=**2**：房主 + `182736023` VK | **slot1=`182736023`**（`host-slots-during-join.jsonl`） |
| ExitSession 后 | 仍可读到「房间用户(4)」 | count=1 | slot1 恢复 **0**（`host-slots-after-exit.jsonl`） |

要点：

- **仅网络加入、未做游戏层握手，已被写入八人玩家记录第 2 席** → 普通 OpenSession 路径**不是**「不占席隐形」。
- 静态一致：SANPK `0x46565b` 通知类型 1 在等待阶段走 `0x4658c0` 填空位；**对局阶段对应分支 RefuseUser**（`RESULT.md` / `host-ui-notification-dispatch.txt`）。
- **未曾出现**「已进 C 层同步接收集合、但不占 SANPK 席 / 不在 Koeinm members」的实测。
- 「房间用户(4)」与 C 层 count=2 **并存**，说明 A 与 C 不可互相替代计数。

### 2.2 alternate-observer（纯 Search / nonjoining）

- `nonjoining_listener*.jsonl`：`SearchSession` 后 `connected=0`、`members=[]`、`cached_commands=0`；**未 OpenSession**。
- `host-before-listen` / `host-after-listen`：房主仍 count=1、slot1=0 → **搜房旁听不占席**。
- `raw-discovery.jsonl`：单包 UDP 发现对目标超时（`error 10060`），`unjoined`；无 join。
- 结论：**B 层发现可以不进 C**；同时 **也没有收到局内同步**（listener 期间无有效对局数据通知）。

### 2.3 ip-state-read（开局后按 IP）

- 局已进小地图；主机 `+0x8410=1`、`+0x8414=0` → SearchSession 响应函数在门关闭时直接返回；定向搜房 `reply_count=0`。
- `SPECTATOR_SCOPE.md`：标准 `NetMsg_SendData` → `0x10005a90` / `0x10005250` **只按已连接成员表群发**；**不把先前搜房者存成独立观战订阅者**。
- 结论：仅提前知悉 IP / 搜过房 **不会**自动变成开局后同步接收方。

### 2.4 「进了游戏侧但不在大厅名单」——已见差异 ≠ 隐形旁观

`PROTOCOL_PRESENCE.md` / Hub `main_lobby`：`0x200b` 拿 grant → `StartServer` 拉起 **自己的** SANPK → 可 `logout` 掉 A 层「房间用户」，他人可能觉得「没经平台就进了游戏」。

这是 **自有会话 + 离大厅** 的存在感折中，**不是**「进别人 C 层却不占席」。

---

## 3. 协议路径评估

| 路径 | 占 C 席？ | 开局后同步？ | 备注 |
| --- | --- | --- | --- |
| OpenSession / Join | **是**（已测） | 若已在 members 内，可能收（未在本轮单独证「持续采集」质量） | 开局后新 Join → RefuseUser |
| 纯 SearchSession | **否**（已测） | **否**（标准路径未见） | 开局后门控常关 |
| raw UDP 发现 | **否** | **否** | 无成员注册则无 SendData 目标 |
| 假想「observer / 旁听 opcode」 | 未知 | 未知 | **未证实**存在合法不占席订阅 |
| 房主/参战方跑 Hub 采集再外送 | 不涉及隐形进房 | **能**（工程路线） | 对方主动授权，与裸旁观不同 |

---

## 4. 已证实 / 未证实 / 风险

### 已证实

1. OpenSession 进自有测试房 → 立即占 SANPK 席 + Koeinm member。
2. 不 OpenSession 的 Search / listen → 不占席、也不进 members。
3. A/B/C 三层可不同步（例：房间用户(4) vs members=2）。
4. 开局后 `EnableJoin` 字段关闭时，标准搜房不回复。
5. 标准 SendData 接收集合 = Koeinm 已连接成员，不是搜房缓存。

### 未证实

1. 任何「不占 maximum/八人席仍进入同步接收集合」的合法协议角色。
2. 开局后持续、完整局内状态（城市/武将/部队）的纯网络旁观。
3. 完全不发 `0x200b` 仍能稳定上生产中继做多线搜房（见 `PROTOCOL_PRESENCE.md` 缺口）。
4. 他人房、满员房、不同线路/中继下的行为外推。

### 风险

| 风险 | 说明 |
| --- | --- |
| 被发现 | OpenSession 会出现在房主玩家席与 members；大厅进出会刷聊天（旧 probe 每轮进出曾导致投诉） |
| 占席 | 等待阶段加入即占八人之一；可能挤掉真人位或改变开局人数 |
| 封号 / 投诉 | live 用 abcde 等已标记账号、无授权进他人房、频繁进出 → **禁止**；本树 `BLOCKED_LIVE_ACCOUNTS` |
| 误伤主号 | 禁止动主号做此类实验；此前临时用主号仅因小号「已登录」阻塞，属例外且已清理 |

---

## 5. 下一步最小实验（仅用户自有测试房；默认本次不做）

前置：干净测试小号、自建空房、书面/当面授权、禁止 abcde、禁止主号、禁止无授权进他人房。

1. **对照 A**：小号只 `Start` + `SearchSession`（不 OpenSession）→ 读房主 members/slots 应不变；确认无同步包。
2. **对照 B**：同号 OpenSession → 确认 slot/member +1；Exit 后恢复（复现 hidden-player）。
3. **开局门控**：开局前后读主机 `+0x8414`；开局后重复 Search，预期无 rooms。
4. **若仍追「不占席同步」**：仅静态/文档继续挖是否存在非 SendData 广播；**动态实验须先证明存在独立订阅结构**，禁止改主机内存绕过 RefuseUser / EnableJoin。
5. **实用数据采集**：授权房主或己方参战进程跑 Hub `room_monitor` 采集外送（与隐形旁观分流）。

---

## 6. 边界（本轮遵守）

- 只读研究与写本文档；未启动监控常驻；未上传 ingest。
- 未使用 claude/codex/grok CLI；未动主号；未 live 用 abcde；未进他人对局。
