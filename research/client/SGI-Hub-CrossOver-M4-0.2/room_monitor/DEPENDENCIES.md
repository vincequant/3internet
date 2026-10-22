# 依赖

- Python 3.9+（系统 `/usr/bin/python3`）
- 本机 Hub 树（`bridge/room_list_reader.py`、Wine 内 Python）
- macOS 上已核验的独立 Wine 运行时（与 Hub `connection.local.json` 相同 wine 二进制，不同 prefix）
- OpenClaw CLI：`/opt/homebrew/bin/openclaw`，Telegram 通道仅 allowlist 私聊
- 可选桌面：`/Applications/Grok Bot.app` 0.29.0（com.anysphere.sand），用于本机对话；主动推送走 OpenClaw

不包含：账号密码、OpenClaw token、Telegram bot token、control.token。
