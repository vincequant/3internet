# 常驻采集器（拿 grant → 离大厅名单 → 周期只搜房）

## 高风险警告（必读）

- **`abcde` 已被盯上 / 有封号风险：禁止再用于任何 live / 生产登录或真连平台实验。**
- **禁止**旧路径：`dashboard` / `native_login_probe` 每约 30s「登录→`0x200b` 进多线2→搜房→`0x2002` 登出」刷进出。
- 改造与验证：**只用 mock / dry-run**。上线前换**干净新小号**，并设环境变量；代码默认拒绝 `abcde`。

## 目标路径

1. （将来 live）干净小号登录一次 + `0x200b` 一次拿 grant。
2. **立刻 `0x2002` 离开大厅** → 不应继续出现在「房间用户」。
3. `StartServer` 一次上中继；周期只 `SearchSession`（不 OpenSession）。
4. 监控周期**不再**反复进出大厅。

详见 `PROTOCOL_PRESENCE.md`。

## 硬约束

- 不碰主号；实验用 mock 或（经用户同意后的）新小号 / `prefix-monitor`。
- 不经大厅 UI（不跑 `SANGUO.exe`）。
- 日志与 status **永不**含密码、token、ingest secret。
- `unconfirmed_empty` ≠ 确认无房 / 已开局。
- 断线重连：指数退避 + 随机抖动。
- **默认不要**在 COM 启生产 live；**不要** `SGI_TK_RESIDENT_LIVE=1`。

## Live 闸门（全部满足才可能真连；仍拒绝 abcde）

```text
SGI_TK_RESIDENT_LIVE=1
SGI_TK_RESIDENT_ALLOW_PROD_LOGIN=1
SGI_TK_RESIDENT_ACCOUNT=<干净新小号，不能是 abcde>
```

缺一不可。`ResidentSession.BLOCKED_LIVE_ACCOUNTS` 含 `abcde`。

## AI Mac 一次实测（风夜）

本机（VKQUANT.AI）受控 once，**不是** COM 常驻 KeepAlive：

```sh
cd research/client/protocol-lab
# 需本机 python32/sgi-protocol-probe.exe + Application Support/SGI-Wine/prefix-monitor
SGI_TK_RESIDENT_LIVE=1 \
SGI_TK_RESIDENT_ALLOW_PROD_LOGIN=1 \
SGI_TK_RESIDENT_ACCOUNT=风夜 \
SGI_TK_RESIDENT_CREDENTIALS="$PWD/query-credentials.fengye.json" \
/usr/bin/python3 bin/sgi_tk_resident.py --live --once --cycles 1 --interval 0
```

- `leave_hall_after_grant` 默认开：login → `0x200b` → 立刻 `0x2002` → 一次 SearchSession → 退出。
- 仍拒绝 `abcde`。不启 sgi-tk-feed，不上传 vkquant ingest。
- `unconfirmed_empty` ≠ 确认无房。

## 文件

| 路径 | 作用 |
| --- | --- |
| `resident_session.py` | 会话 + mock + opcode 账本；默认 `leave_hall_after_grant` |
| `loader_resident.py` | Wine：StartServer 一次，stdin 触发 SearchSession |
| `bin/sgi_tk_resident.py` | 常驻主进程；默认 dry-run |
| `bin/start-resident.sh` / `stop-resident.sh` | 启停（默认 dry-run） |
| `dashboard.py` | 只读常驻状态，禁止再调 probe |
| `test_resident_session.py` | mock：离名单后多次 search 不发大厅进出 |
| `sgi_tk/PROTOCOL_PRESENCE.md` | 协议结论 |
| `sgi_tk/RESIDENT_RUNBOOK.md` | 本文 |

## 本地验证（本机源码树，不连生产）

```sh
cd research/client/protocol-lab
/usr/bin/python3 -m unittest test_resident_session.py -v
/usr/bin/python3 bin/sgi_tk_resident.py --dry-run --cycles 4 --interval 0
```

预期：

- `login_count == 1`，`enter_count == 1`，`logout_count == 1`（logout 在拿 grant 后立刻发生）
- 多次 search 期间大厅 opcode 不再增加
- `hall_presence == left_after_grant`，`room_list_visible_expected == false`
- `account == mock-alt`（不是 abcde）
- `assert_not_on_room_list` / `assert_no_reenter` 为 true

## 采集机同步（可选；勿启 live）

源码在 VKQUANT.AI；COM：`/Users/vkquant/sgi-protocol-lab-20260915/`。

```sh
# 示例：rsync 文件即可，不要 SGI_TK_RESIDENT_LIVE=1
rsync -av --relative \
  research/client/protocol-lab/./resident_session.py \
  research/client/protocol-lab/./loader_resident.py \
  research/client/protocol-lab/./dashboard.py \
  research/client/protocol-lab/./test_resident_session.py \
  research/client/protocol-lab/./bin/sgi_tk_resident.py \
  research/client/protocol-lab/./bin/start-resident.sh \
  research/client/protocol-lab/./bin/stop-resident.sh \
  research/client/protocol-lab/./sgi_tk/RESIDENT_RUNBOOK.md \
  research/client/protocol-lab/./sgi_tk/PROTOCOL_PRESENCE.md \
  research/client/protocol-lab/./login_protocol.py \
  research/client/protocol-lab/./koeinm_probe.py \
  vkquant@fd7a:115c:a1e0::f930:8943:/Users/vkquant/sgi-protocol-lab-20260915/
```

COM dry-run（仍不登生产）：

```sh
ssh vkquant@fd7a:115c:a1e0::f930:8943 \
  'cd /Users/vkquant/sgi-protocol-lab-20260915 && /usr/bin/python3 bin/sgi_tk_resident.py --dry-run --cycles 3 --interval 0'
```

### 与旧 sgi-tk-feed

- **不**自动 bootstrap `com.vkquant.sgi-tk-feed` / dashboard LaunchAgent。
- 重开 feed 前：常驻 mock/新小号路径已验证；`room_list_visible_expected` 保持 false；聊天不再刷进出。

## 状态字段

`hall_presence`、`room_list_visible_expected`、`presence_mechanism`、`enter_count` / `logout_count` / `login_count` / `search_cycles` / `session_id`、`opensession_join`。

## VKQUANT.AI 日常常驻（风夜 live）

`abcde` 彻底弃用。本机日常用 **风夜** + `leave_hall_after_grant`（默认开）。

```sh
cd research/client/protocol-lab
SGI_TK_RESIDENT_LIVE=1 \
SGI_TK_RESIDENT_ALLOW_PROD_LOGIN=1 \
SGI_TK_RESIDENT_ACCOUNT=风夜 \
SGI_TK_RESIDENT_CREDENTIALS="$PWD/query-credentials.fengye.json" \
./bin/start-resident.sh
```

- 成功后 `resident.pid` 有进程；`resident-status.json` / `http://127.0.0.1:18774/api`：`hall_presence=left_after_grant`，会话内 `enter_count==1`，无反复进出。
- 上传：本机 `~/Library/Application Support/SGI-TK-Feed` 的 `sgi_bot_client.py` **默认读本机常驻**（`SGI_MONITOR_SOURCE=local`），`run.sh` + LaunchAgent `com.vkquant.sgi-tk-feed` 周期 POST ingest（token 仅 `~/.config/sgi-tk/ingest.env`）。
- 超 3 告警：`sgi-tk-watch-alert` 读公开 `https://www.vkquant.ai/api/public/sgi-tk/latest`，阈值 `THRESHOLD`（默认 ≥3）。
- 当前常驻代码**无** Asia/Shanghai 09:00–00:00 静默窗口；若以后加上则遵守。
- **禁止**回退到 abcde；失败就报失败。

