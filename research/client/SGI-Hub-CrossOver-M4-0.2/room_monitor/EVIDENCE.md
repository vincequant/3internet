# 0.1.1 本机验证（2026-09-15）

## 产物状态

| 项 | 状态 |
|---|---|
| 读取器多实例 / 事件引擎 / OpenClaw 适配 | 已实现、已单测 |
| 独立 prefix-monitor | 已创建并核验隔离 |
| 软件包 0.1.1 | 已安装、已升级（配置保留） |
| OpenClaw 测试私聊 | 已发送且 `ok: true` |
| 小号凭据 | 已就绪（钥匙串，用户名 vinceost，密码不落盘） |
| 监控大厅 | 已在 prefix-monitor 启动（SANGUO 64439） |
| 登录/列表/30 分钟 | 被「用户已经登录」挡住；未再循环交密码 |

## 独立 prefix

- 路径：`~/Library/Application Support/SGI-Wine/prefix-monitor`
- 未复制：`UserConfig.ini`、`3I/Save`、`sgi-crash-context.bin`
- 新 UserConfig：用户名空、密码空、`LoaderUdpPort=4578`
- SANPK SHA256：`1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2`（与主号相同）
- 主号 SANPK：PID 49801，cwd=`prefix-sikarugir10/.../3I`，起于 23:52:12，provision/install/upgrade 后仍在
- 监控 wineserver 在配置完成后已按 **该 prefix 的** `wineserver -k` 停掉；未对主号 wineserver 操作

2026-09-15 00:21 后：凭据就绪后仅在 `prefix-monitor` 启动 SANGUO（PID 64439）。主号 SANPK 49801 / wineserver 49714 未动。登录窗可见；提交后提示「用户已经登录」。勾选强制登录后再提交一次仍同错。已停止自动交密码。

2026-09-15 00:29：用户截图确认监控登录框/提示框中文乱码（横幅正常）。根因是独立 prefix 缺少主号那组字体替换（宋体/SimSun/MS Shell Dlg → Arial Unicode MS），MessageBox 走 Tahoma/SimSun 无汉字。已写入相同 Replacements/FontSubstitutes，并只重启监控大厅（新 SANGUO 68620）。主号 49801 未动。不再自动交密码。

## 软件包

- 版本 0.1.1
- 安装树：`~/Library/Application Support/SGI-Room-Monitor/opt`
- 入口：`~/bin/sgi-room-monitor`
- 技能：`~/.openclaw/workspace/skills/sgi-room-monitor/SKILL.md`
- tgz SHA256：`e6e0d68e37d09b14e68411a01ab8b597fa6618b7ec9f1f33f675e150e8678b34`
- 升级后 `monitor_prefix`/`main_prefix` 仍在

## 测试

- `unittest discover -s room_monitor/tests`：21 passed
- `unittest discover -s bridge`：225 passed
- 安装脚本内再跑 21 passed

## OpenClaw

- CLI：`openclaw message send --channel telegram --target <allowlist> --message …`
- 本轮回执：`target_kind=telegram_dm`，`ok: true`
- 正文以【监控测试】开头，声明不是人数报告
- Grok Bot.app 未改包体
