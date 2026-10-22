# Linux Grokbot 交接（房间监控）

给「一直开着的 Linux Grokbot」用。Mac 侧 VKQUANT.AI 已能登录小号大厅；Linux 是常开采集候选，不是把 Mac 包直接跑起来。

## 目标

在 **Linux 主机**上用独立 Wine 挂小号，停在 SANPK「游戏选择」，周期读 `n/8`，只向用户本人私聊汇报。用户关掉 VKQUANT.AI 后仍要能盯列表。

平台没有公开人数接口。不登录、不进游戏选择，任何 Bot 都看不到房间。

## 先读

- `room_monitor/README.md`
- `room_monitor/USAGE.md`
- `room_monitor/EVIDENCE.md`
- `room_monitor/DEPENDENCIES.md`
- `room_monitor/grokbot_skill/SKILL.md`
- `bridge/room_list_reader.py`、`bridge/room_list_probe.py`、`bridge/room_instance.py`
- `sgi_room_monitor/provision.py`（独立 prefix、排除项、UDP 4578、CJK 字体替换）

## 禁止

- 不要改游戏 EXE、不要写游戏内存、不要覆盖存档。
- 不要复制或读取主号 `UserConfig.ini`、`3I/Save`、`sgi-crash-context.bin`、登录缓存、钥匙串、`credentials.json` 里的密码、OpenClaw token、Telegram bot token。
- 不要对主号 prefix 执行 `wineserver -k` / `killall wine`。只允许 `WINEPREFIX=<监控prefix> wineserver -k`。
- 不要动 VKQUANT.AI 主号：`prefix-sikarugir10`，SANPK 历史上 PID 49801，cwd 在该 prefix 的 `3I`。
- 不要把 `~/Library/Application Support/SGI-Wine/runtime-sikarugir10` 或整个 Mac prefix 当 Linux 可执行包。
- 不要循环提交密码。验证码 / 账号异常 /「用户已经登录」停下来问用户。
- 不要加入、创建、开始对局。只停在游戏选择列表。
- 不要把人数失败报成 0 人。已开局不可观测。
- 不要往群或平台公共聊天发监控。

## Mac 上已成立（不要重做一遍当「Linux 已完成」）

- 工程：`/Users/vk/Documents/Coding/三国志internet`
- Hub：`research/client/SGI-Hub-CrossOver-M4-0.2`，版本看 `RELEASE.json`，目录名 0.2 是历史名。
- 主号 Wine：`~/Library/Application Support/SGI-Wine/prefix-sikarugir10` + `runtime-sikarugir10`（Wine 10 Sikarugir）。
- 监控 Wine：`~/Library/Application Support/SGI-Wine/prefix-monitor`（wineboot 新注册表，UDP **4578**）。
- 服务：`~/Library/Application Support/SGI-Room-Monitor/`，入口 `~/bin/sgi-room-monitor`。
- 技能：`~/.openclaw/workspace/skills/sgi-room-monitor/SKILL.md`（本机 OpenClaw，不是 Linux）。
- 小号用户名 `vinceost` 已在 **Mac 钥匙串**；密码不进仓库。Linux 必须让用户在 Linux 本机重新 `creds-set`，不要拷钥匙串。
- 2026-09-15：监控大厅已登录 `vinceost`（标题含当前用户）。中文乱码已用字体替换修好：宋体/SimSun/MS Shell Dlg/Tahoma → Arial Unicode MS。ACP=936。缺替换时提示框变圆圈。
- 自动登录曾报「用户已经登录」；用户后来本人强制登录成功。不要再自动交密码。
- 列表刷新、进多线2、点启动游戏、30 分钟浸泡：**Mac 上尚未完成**。Linux 更未开始。
- 单元测试（Mac 源码）：`room_monitor/tests`、`bridge` 的 unittest。改读取器后两边都要跑。

## 架构（不要搞反）

| 角色 | 是什么 | 不是什么 |
|---|---|---|
| 采集端 | 有桌面的机器 + Wine + 小号停在游戏选择 | 云端对话模型 |
| Grokbot/Telegram | 问「现在几个人」并私聊回报 | 游戏宿主 |
| 本机 Grok Bot.app | VKQUANT.AI 上的桌面壳 | 常开 Linux |
| 你（Linux Bot） | 候选常开采集机 | 不能直接执行 Mac Wine |

Mac 软件包 / Sikarugir runtime **不能**在 Linux 上运行。要迁的是做法，不是 `wswine.bundle`。

## 你这边第一步（先回报，再装）

在 Linux 本机执行并贴回原文（可打码主机名以外的秘密）：

```bash
uname -a
id
echo "DISPLAY=$DISPLAY WAYLAND=$WAYLAND_DISPLAY"
command -v wine; wine --version || true
command -v python3; python3 --version
df -h
ls -ld "$HOME" /opt /usr/share/fonts 2>/dev/null
```

没有可用 DISPLAY/Wayland（纯 SSH 无桌面）时：**停**。先解决图形，再谈 Wine。无头 Wine 对这个 Delphi 大厅没有验证过。

## Linux 允许做的复制（用户明确同意后）

从 Mac **只拷游戏程序/资源**，排除登录与存档：

- 源：`prefix-sikarugir10/drive_c/sgi/run-3.5` 或 `prefix-monitor/drive_c/sgi/run-3.5`
- 排除：`UserConfig.ini`、`3I/Save`、`sgi-crash-context.bin`、任何密码文件
- SANPK SHA256 必须仍是 `1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2`
- Linux 自己 `wineboot` 新 prefix，自己写空 `UserConfig.ini`（gb18030，`RemberPwd=False`，`LoaderUdpPort` 不要用 4576/4577，避免和主号抢）
- 装 CJK 字体并做与 `provision.apply_cjk_fonts` 相同的替换；`LANG=zh_CN.UTF-8`，GetACP=936
- 源码用仓库 `room_monitor/` + `bridge/`，不要拷 Mac 的 `credentials.json` / `control.token` / OpenClaw 配置

## 成功标准

1. Linux 上独立 prefix 的 SANGUO 能显示中文（不是圆圈乱码）。
2. 小号登录一次；验证码或「已登录」则停，不循环。
3. 进入三国对战房 / 多线2（主线），点启动游戏，出现「游戏选择」。
4. `room_list_reader` 带 `--prefix <linux-monitor-prefix>` 读到真实 `n/8`（含房主）。空列表必须与界面核对，不能当 0 人。
5. 只向用户本人私聊发**真实**列表，不要合同里的示例房间。
6. 不加入/建房/开局。主号（若同网或同机）不被 `wineserver -k`。
7. VKQUANT.AI 关机后，Linux 采集仍在。

## 建议顺序

1. 能力探测（上一节命令）。
2. 写 `LINUX_PROBE.md`：发行版、有无桌面、Wine 能否装、磁盘。
3. **不要**先宣布「已迁到 Linux」。
4. 有桌面后再装发行版 Wine（或确认已有），wineboot，拷游戏资源，CJK，空 UserConfig。
5. 用户在 Linux 本机输入小号密码。
6. 登录 → 启动游戏 → 接上现有 reader/service。
7. 技能装到 **Linux 这台**的 OpenClaw/Grokbot workspace，命令仍是 `sgi-room-monitor …`。

若 Linux 无桌面或 Wine 装不上：明确写 BLOCKED，建议改挂 **VKQUANT-COM**（已有同套 Mac Wine/游戏），不要硬做无头方案。
