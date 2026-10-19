# 帐号密码独立搜房实验：2026-09-15

## ⚠ 日常监控账号（现行）

- **`abcde` 已彻底弃用**：高风险 / 有投诉封号迹象，列入 `ResidentSession.BLOCKED_LIVE_ACCOUNTS`，禁止任何 live / 生产登录。
- **日常正常监控账号：`风夜`**（凭据 `query-credentials.fengye.json`，0600；永不打印密码）。
- **策略：`leave_hall_after_grant`**：拿 grant 后立刻 `0x2002` 离大厅名单，之后周期只 `SearchSession`；禁止旧路径反复 `0x200b`/`0x2002` 刷进出。
- 启停与验证见 `sgi_tk/RESIDENT_RUNBOOK.md`。本机（VKQUANT.AI）用 `bin/start-resident.sh` live + 本机 `SGI-TK-Feed` 读常驻 HTTP/status 上传 ingest；不依赖 COM。

---

## 历史记录：曾用小号 abcde（已弃用，勿再用）


用户新注册的专用监控小号已切换到 `abcde`。凭据只存放在另一台 Mac 的
`~/sgi-protocol-lab-20260915/query-credentials.json`（0600），不写入源码或网页。
旧监控软件的凭据存储未覆盖。本轮确认注册后 abcde 大厅仍在线，退出该账号的
远端大厅 PID 8090 后，独立登录及搜房通过。

实时页面：**http://127.0.0.1:18773/**。

- `dashboard.py` 在 VKQUANT-COM 运行，只监听本机回环地址。
- 本机通过 SSH 隧道查看同一页面；已在 Codex 浏览器打开。
- 页面展示房间名、房主、人数、最近更新时间和列表变化记录。
- 页面约每 30 秒触发一次完整查询，页面状态每 2 秒刷新。不是服务器推送。
- 关闭所有查看页面后，最多 45 秒内停止新增查询；当前查询正常结束。
- 数据过期、查询失败和未收到房间都明确显示，不将旧数据当作新结果。
- 服务只提供 `/` 和 `/api`，不提供目录浏览、源码或凭据文件下载。
- 注册后的 abcde 在另一台 Mac 原游戏 prefix 登录；查询仍在独立 monitor prefix 执行。
  本机主号未操作。

已验证页面真实显示两个 `SGZWLB`：`VK(筑基期) 1/8`、`ok-007 1/8`。
这是验证时的记录，当前状态以页面时间为准。

服务文件位于远端实验目录，PID 记录在 `dashboard.pid`，日志 `dashboard.log`。
本机隧道 PID 记录在本目录 `evidence/dashboard-tunnel.pid`。
目前未设为开机自启；远端重启后可从实验目录运行 `python3 dashboard.py`。
本机隧道重建命令：

```sh
ssh -N -L 127.0.0.1:18773:127.0.0.1:18773 vkquant@fd7a:115c:a1e0::f930:8943
```

## 最新结果：已打通无大厅、无游戏的完整搜房

22:37 左右，用户新建房间后，在 **VKQUANT-COM 小号 vinceost** 上实测成功：

`本地小号凭据 → Python TCP 登录 → 多线2进房授权 → 原版转发 DLL → 搜房 JSON`

- 两次独立登录均读到：`SGZWLB / VK(筑基期) / 1/8`，房间 ID `171274991`。
- 全链路耗时约 12.2 / 11.9 秒；每轮包含三次搜索。
- 未运行 SANGUO.exe 或 SANPK.exe，不读取其内存，不截图识别列表。
- 登录、目录、进房授权、在线成员由原生 Python 协议实现。
- 最后一段转发和搜房仍复用原版 NetHookLoader / NetHookCore / Koeinm DLL，Mac 上通过 Wine 运行。
- **仅帐号密码作为登录输入已实测可行，不等于无 DLL / 无 Wine。**
- 所有动态操作只在另一台 Mac 的小号进行，本机主号没有操作。

因此，“必须运行完整大厅和游戏才能拿到列表”已被本次实验否定。
是否存在官方公开 API 并未确认；本实现来自已安装客户端的协议分析。

### 使用

另一台 Mac 上：

```sh
~/bin/sgi-room-query
```

本机通过 SSH 查询另一台 Mac：

```sh
ssh vkquant@fd7a:115c:a1e0::f930:8943 '~/bin/sgi-room-query'
```

更新实验脚本并查询：

```sh
python3 research/client/protocol-lab/run_native_remote.py
```

结果是 JSON，包含 `rooms`、`query_status`、`observed_at`。
`replies_received` 表示收到真实响应；`unconfirmed_empty` 只表示未收到房间，
不可据此断言已经开局或平台无房。小号大厅/游戏仍运行时会拒绝开始，以免会话冲突。
凭据从远端现有监控凭据存储读取，不通过参数、聊天或日志传递。
每次查询结束关闭自己的连接与实验进程，无常驻后台服务。

### 当前边界

| 环境或功能 | 状态 |
| --- | --- |
| 另一台 Mac：仅凭据、无大厅/游戏搜房 | 真实房间通过，重复验证通过 |
| 原生 Python 登录、进房、成员名单 | 通过，不依赖 Wine |
| 完全去掉原版 DLL / Wine | 尚未实现 |
| Windows、Linux/grokbox 实机 | 尚未验证；当前运行器限制在授权的第二台 Mac |
| 长时间监控、断线重连、开局确认 | 尚未验证，列表消失不能直接等同开局 |
| Grok Bot 接入新查询命令 | 尚未修改，现有 Bot 不会自动切换 |

### 本轮新增文件

- `login_protocol.py`：传输封装、字节映射、CRC、登录与目录解析，纯 Python 标准库。
- `native_login_probe.py`：独立认证、选择正确的游戏分类及多线2、进房和调用转发探针。
- `loader_probe.py`：在独立 Win32 进程初始化原版转发 DLL，通过 stdin 接收临时授权，退出时清理。
- `run_native_remote.py`：只部署白名单脚本到第二台 Mac，保存脱敏证据并输出简短结果。
- `test_login_protocol.py`：校验已知编码向量、分片/合包、损坏报文、登录字段。
- `pe_static.py`：只读 PE 分析辅助工具。

关键协议定位：TCP 外封装位于 SANGUO VA `0x636384`；登录字段 `0x63d6bc`；
TCP CRC `0x63b298`；登录 `0x2001`、认证开始/结束 `0x2010/0x2011`、
游戏/房间目录 `0x2012/0x2013`、进房 `0x200b`、成员请求 `0x200f`。
先选“三国对战房”的 game_id，再选“多线2”，避免误入文明4或其他游戏的同名线路。

本轮曾退出原小号大厅 PID 59058；窗口关闭实际会最小化，因此在确认无游戏后只对该
精确路径和 PID 发送 SIGTERM。恢复官方客户端对照的启动尝试退出，未作为成功对照；
随后用户确认当时确实空列表，并亲自新建测试房间，完成正向验证。
一次只针对 monitor prefix 的 wineserver reset 返回 1，未报告重置成功。
未更改任何原版 EXE/DLL、主号凭据或游戏存档。

## 以下为第一阶段历史记录（当时仍依赖大厅）

### 当时结论

在 **VKQUANT-COM 的小号 prefix-monitor** 上，已实测：保留已登录的 SANGUO 大厅，
独立 32 位 Python 进程加载原 Koeinm.dll 和 NetHookCore.dll，可以查询真实房间；
**无需运行 SANPK.exe，也无需游戏选择窗口**。

这不是纯协议登录客户端。帐号密码认证、进频道和平台会话仍由现有大厅承担。
本次没有读取密码、重登帐号、加入/创建/开始对局，也没有修改游戏 EXE 或游戏进程内存。
用户指定本机主号不动，因此全部动态实验均经 SSH 在另一台 Mac 上执行。

## 对照结果

| 实验 | 结果 |
| --- | --- |
| Koeinm 独立初始化 + 本机回环合成响应 | 成功；4 字节查询、78 字节响应、80 字节内部记录 |
| 真实端口/应用标识，无 NetHookCore | 调用返回 0，但无回应；不能当作真实空房间 |
| 加载 NetHookCore，实验进程显示 Windows 10 | 无回应 |
| 加载 NetHookCore，仅实验程序改为 Windows 8.1 | 成功收到真实房间，约 1.28 秒 |
| 关闭本次启动的远端 SANPK 后重新查询 | 两次成功，约 1.39 / 1.28 秒 |

真实对照记录：房间 `SGZWLB`，房主 `神行神打神将神卡`，连接人数 `3/8`，
房间标识 `170604735`。原客户端当时读取结果相同。
这是实验时的观测，不是阅读本文时的实时状态。
同轮网络可能返回三份相同房间，脚本按标识/房名/房主去重并保留 reply_count。

最终远端进程核对：小号 SANGUO 仍为本来运行的 macOS PID 59058；
无 SANPK、无残留实验进程。未启动新后台监控。

## 技术发现与边界

- `NetMsg_SearchSession` 接受目标地址、结果 HWND 和消息号。
- HWND 为 NULL 时，原 DLL 使用 PostMessageA 把结果交给调用线程消息队列；
  脚本用 PeekMessageA 取回记录，不创建可见窗口。
- 原游戏实测网络参数：端口 7777，应用标识 78731，最大槽位 8。
- 原 Koeinm 搜索实现发送网络字节序的 4 字节应用标识。
- `NetHookCore.dll` 的相关初始化在 RVA 0x6300 的流程中检查 GetVersionExA，
  只进入 major 5/6 的分支。本次默认 Python 报 10.0.19043，切为 6.3.9600 后成功。
  这是本次失败对照的原因证据，不能据此断定过去所有漏房间都由版本造成。
- 查询程序只加载 NetHookCore 到自身；不调用 LoadHook 去操作其他进程。
- 复用的是远端已有大厅会话；未重新验证频道内部 ID，也未验证冷启动登录全链路。
- NetMsg_Start 的九参数采用静态分析所得的最小实验组合；未声称所有字段语义都已还原。
- DLL 返回 0 仅表示搜索例程结束，不代表收到有效房间或网络畅通。
- 尚未验证大厅关闭后的持续查询、无大厅认证、Linux/Windows 实机、长期稳定性、开局事件。

## 文件

- `koeinm_probe.py`：Win32 独立查询与回环验证，校验 DLL 哈希；不访问任何游戏进程。
- `run_remote.py`：仅面向已授权 VKQUANT-COM 小号的实验运行器。
- `monitor_inspect.py`：远端小号窗口枚举，以及显式参数指定的启动/关闭测试游戏操作。
- `monitor_net_read.py`：仅只读检查已审计 DLL 的网络字段。
- `evidence/`：真实执行 stdout/stderr、客户端对照和最终进程记录；合成响应明确带 synthetic=true。

## 重跑当前实验

在本源码仓库执行以下命令。前提：远端小号大厅已登录并在目标频道、网络可达。
命令不会启动 SANPK，不会登录或提交密码。

```sh
python3 research/client/protocol-lab/run_remote.py koeinm_probe.py \
  --target 255.255.255.255 --port 7777 --app-id 78731 --with-nethook --wine81
```

输出 `query_status=replies_received` 时查看 rooms。
`unconfirmed_empty` 表示本轮没有收到记录，不能翻译成“平台没有房间”。
`credentials_only_verified=false` 始终保留，避免 Bot 把本实验误报为纯帐号密码方案完成。

回环测试（只生成本机合成数据）：

```sh
python3 research/client/protocol-lab/run_remote.py koeinm_probe.py --loopback-fixture
```

## 远端变更和移除

实验目录为 `/Users/vkquant/sgi-protocol-lab-20260915/`，包含独立 Win32 Python、脚本和证据。
使用已存在的原 DLL，没有覆盖游戏文件。
仅在小号 prefix-monitor 中增加实验 EXE 专属的 Wine 配置：
`HKCU\Software\Wine\AppDefaults\sgi-protocol-probe.exe` 的 `Version=win81`。
主号配置、全局 Wine 版本和原 python.exe 的兼容设置未改。
移除实验时删除该专属注册表键及实验目录即可；不需要停止大厅或 wineserver。

Windows 原生调用与 Linux Wine 复用同 DLL 在架构上有后续验证价值，但本次仅 Mac/Wine 实测通过。
