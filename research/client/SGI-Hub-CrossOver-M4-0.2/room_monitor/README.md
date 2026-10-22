# SGI 小号房间监控 0.1.0

独立于 Hub 界面的后台服务：小号停在 SANPK「游戏选择」列表，周期刷新人数，只通过本机 OpenClaw Telegram 私聊向用户本人汇报。

## 两端

- **Grokbot 端**：本机 OpenClaw（`~/.openclaw`，Telegram allowlist 私聊）+ 可选桌面 `Grok Bot.app`。技能：`grokbot_skill/SKILL.md`。
- **游戏监控端**：独立 Wine prefix 里的平台小号 + SANPK。默认与本机 Grokbot 同机（VKQUANT.AI / macOS arm64）。常开 Linux 迁徙见 `GROKBOT_LINUX_HANDOFF.md`；不要把采集端假设成无桌面 Linux，也不要直接跑 Mac Sikarugir 包。

## 安装

```bash
sh research/client/SGI-Hub-CrossOver-M4-0.2/room_monitor/packaging/install.sh
```

安装位置：`~/Library/Application Support/SGI-Room-Monitor/opt`  
本机配置：`~/Library/Application Support/SGI-Room-Monitor`（不进发布包；本机 `~/Applications` 为 root 所有，故不写那里）

再编辑本机 `config.json`：

- `monitor_prefix`：小号专用 Wine prefix，不能等于主号 prefix
- `main_prefix`：主号 prefix，用于拒绝误操作
- `hub_root`：安装脚本会写入当前 Hub 树
- `account_username`：小号名
- 密码：本机执行 `sgi-room-monitor creds-set`（钥匙串优先）

## 命令

`sgi-room-monitor start|list|pause|resume|status|stop`  
`sgi-room-monitor cmd "现在几个人"`

或对 Grokbot 说：开始监控 / 现在几个人 / 只看等待 / 设置人数提醒 5 / 调整刷新间隔 20 / 暂停 / 恢复 / 停止 / 健康状态。

## 口径

人数是游戏选择 `n/8`（含房主）。平台「房间用户(N)」是另一口径。已开局状态不可观测。失败不会报成 0 人。

## 回滚

`sh packaging/uninstall.sh` 只删本服务安装与 LaunchAgent，不关主号、Hub、游戏。配置目录保留。升级用 `packaging/upgrade.sh`，会备份 `config.json`。
