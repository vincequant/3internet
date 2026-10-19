# 协议存在感：为何会上「房间用户」，以及如何尽量不露名单

证据目录：`evidence/hidden-player-check-20261007/`、`evidence/alternate-observer-paths-20261007/`。  
Hub 对照：`SGI-Hub-CrossOver-M4-0.2/room_monitor/sgi_room_monitor/{protocol_session,sanpk_takeover,main_lobby}.py`。

## 两层名单（勿混谈）

| 层 | 通道 | 名单 | 触发 |
| --- | --- | --- | --- |
| 平台大厅 | TCP `25001` | 「房间用户」+ 聊天「进来了/离开了」 | `0x200b` ENTER 多线2；`0x2002` LOGOUT 离开 |
| 对战房间 SANPK | Koeinm / NetHook（OpenSession） | 游戏内玩家席位 | `_NetMsg_OpenSession` 网络加入 |

监控房间**列表**只需要：大厅 grant → `StartServer` 上中继 VPN → `SearchSession`/UDP 搜房。  
不需要 OpenSession 进别人的对战席（`raw_nonjoining_search` / nonjoining listener 已证明搜房可不 join）。

## 为何 native_login_probe / 旧常驻会进「房间用户」

1. `0x2001` 登录后目录下发 `0x2012`/`0x2013`。
2. 客户端发 `0x200b` + 多线2 `room_id` → 平台把账号记入该线房间成员。
3. `0x9000` enter-ack 带回 relay grant（virtual_ip / token / user_id…）。
4. 旧 `native_login_probe`：**每轮** login→enter→StartServer 搜房→`0x2002` 登出 → 聊天刷进出（abcde 因此被投诉；**高风险，禁止再用**）。
5. 「进房后一直不登出」的常驻：少刷进出，但**一直挂在房间用户名单上**。

## 「协议启游戏却不在房间名单」的实际差异

Hub `HallSession.login_and_enter` **同样发 `0x200b`** 拿 grant；差异在拿 grant 之后：

1. `try_launch_playable_sanpk` / 原版 `StartServer` 用 grant 拉起 SANPK（游戏侧在线）。
2. `HallSession.close(logout=True)` 可关掉 TCP 大厅会话 → 平台「房间用户」掉线。
3. SANPK 可因 StartServer 仍保持；他人看见「进了游戏」而大厅 UI 未必有此人（见 `main_lobby._attach_sanguo_after_protocol` 注释：别人问怎么没经过平台就进了游戏）。
4. `hidden-player-check`：仅 OpenSession 网络加入**会占 SANPK 席位**；那是另一层，不是大厅名单。

结论：**不露大厅名单 ≠ 从不发 `0x200b`**。当前公开证据下，生产中继 grant/token **仍需一次 `0x200b`**。可行折中：进房拿 grant → **立刻 `0x2002` 离大厅** → 只用 StartServer + SearchSession 周期搜房（本树默认 `leave_hall_after_grant`）。

## 零进房路径的缺口

- 仅登录不进房：能收目录，**无 enter-ack grant** → 无法 `StartServer` 上生产中继。
- `raw_nonjoining_search`：UDP 发现；在已有 VPN 身份时可搜；无独立大厅 grant 时对指定 host 曾超时（见该证据 jsonl）。
- **尚未证明**：完全不发 `0x200b` 仍能稳定监控多线2 对战房间列表。

## 本树采用的机制（mock 可证）

- `presence_mechanism=leave_hall_after_grant`
- 账本：establish 期 `login=1, enter=1, logout=1`；之后 N 次 `search_once` **不再**发 `0x2001/0x200b/0x2002`
- `hall_presence=left_after_grant`，`room_list_visible_expected=false`
- `opensession_join=false`（搜房路径不 OpenSession）
- **abcde**：代码 `BLOCKED_LIVE_ACCOUNTS`；live 需干净新小号 + 显式环境闸门，默认全关
