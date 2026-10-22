# 使用说明

1. 安装：`sh packaging/install.sh`
2. 在 `~/Library/Application Support/SGI-Room-Monitor/config.json` 填独立 `monitor_prefix` 与 `main_prefix`。
3. 小号凭据入口（必须由你在本机完成，不要发到聊天）：
   `sgi-room-monitor creds-set`
   优先写入 macOS 钥匙串服务 `sgi-room-monitor`。失败时才写同目录 `credentials.json`（600）。
   查看是否已配置：`sgi-room-monitor creds-status`（只显示是否就绪，不打印密码）。
4. 确认主号大厅/游戏/Hub 继续运行；本服务不会去关它们。
5. 对 Grok Bot.app 说「现在几个人」时，它应在跑监控的 Mac 上执行 `sgi-room-monitor brief`，禁止用空白「游戏选择」截图判断。与 IB / 证券帐号无关。
   进列表：`sgi-room-monitor ensure`（登录→多线2→启动游戏，需本机已 `creds-set`）。
   单次查询：`sgi-room-monitor query`。一句话：`sgi-room-monitor brief`。持续监控：`sgi-room-monitor start`。
6. 若出现验证码或账号异常，服务会私聊要求本人处理，不会循环交密码。监控大厅中文乱码时，先补 `prefix-monitor` 的字体替换再重启该大厅，不要动主号。
7. 到达游戏选择后，服务只刷新列表，不加入、不建房、不开局。
8. 查询：`现在几个人`；暂停/恢复/停止用对应中文或 CLI。
9. 停止：`sgi-room-monitor stop`。只停本服务及其 127.0.0.1 控制口。
