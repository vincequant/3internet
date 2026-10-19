# SGI /tk 房间馈送运维

专用小号采集器把多线2房间快照上传到 Cloudflare Worker，`https://vkquant.com/tk` 每 10 秒读取公开接口。

## 主机

- 采集：VKQUANT-COM，`/Users/vkquant/sgi-protocol-lab-20260915/dashboard.py`，`127.0.0.1:18773`
- 调度：本机 VKQUANT.AI（Grok Bot.app 所在机）。未发现独立名为 Grokbox 的 SSH 主机；本机 LaunchAgent 在关闭网页后继续跑，不调用模型。
- 网站：大陆站 Tencent `/srv/www/vkquant.com` 只加 `/tk`；API 在现有 Worker + D1。

## 启动

```sh
# Bot 调度（本机）
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.vkquant.sgi-tk-feed.plist"

# 采集恢复（仅 VKQUANT-COM，不杀 Wine / 主号）
ssh vkquant@fd7a:115c:a1e0::f930:8943 'launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.vkquant.sgi-tk-dashboard.plist"'
```

## 停用

```sh
launchctl bootout gui/$(id -u)/com.vkquant.sgi-tk-feed
ssh vkquant@fd7a:115c:a1e0::f930:8943 'launchctl bootout gui/$(id -u)/com.vkquant.sgi-tk-dashboard'
```

采集恢复停用后，已在跑的 `dashboard.py` 不会自动退出。不要 `killall wine` 或结束主号。

## 回滚

大陆站 `/tk`：

```sh
ssh root@175.178.238.94 'ln -sfn /srv/www/vkquant.com/releases/<previous> /srv/www/vkquant.com/current && systemctl reload nginx'
```

Worker：用发布前的 `cloudflare.js` 再跑 `scripts/deploy_worker.sh`。上传密钥只存在本机 `~/.config/sgi-tk/ingest.env` 和 Cloudflare secret，不进仓库或页面。

## 日志

- 本机：`~/Library/Logs/sgi-tk-feed.jsonl`、`sgi-tk-feed-state.json`
- 采集：`/Users/vkquant/sgi-protocol-lab-20260915/dashboard.log`
- 身份验证失败会暂停调度并写 `needs_attention=true`，不会密集体重试。


## 常驻采集（2026-10-09）

旧 dashboard 每轮整段 `native_login_probe`（登录→进房→搜房→登出）会刷聊天进出；**abcde 高风险，禁止再用该路径真连**。
改用常驻：`leave_hall_after_grant`（拿 grant 后立刻离大厅名单）+ 周期只搜房。见 `RESIDENT_RUNBOOK.md`、`PROTOCOL_PRESENCE.md`。
默认 dry-run / mock；live 需干净新小号与显式闸门，代码拒绝 `abcde`。不要自动 bootstrap 旧 feed。
