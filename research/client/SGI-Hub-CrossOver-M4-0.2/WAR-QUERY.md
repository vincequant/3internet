# 全知战局只读查询

录像缺陷未在运行中的采集桥上启用前，**不能把连续分析当成已可靠**。磁盘工作区 1.1.139 已有查询层、磁盘游标补传、私有 HTTP 和只读 MCP。当前进程仍可能是旧桥。

## 本地查询（不启动游戏或采集桥）

```text
./Start-War-Query.command summary --demo
./Start-War-Query.command events --demo --start 2 --end 10
./Start-War-Query.command track --demo --unit-id 7
```

默认全知数据。`player_identity.confirmed=false` 时不猜测我方。

返回字段：`match_id`、`seq`、`snapshot_id`、`capture_end`、`freshness`、`gaps`、`completeness`。`visual_interpolation` 恒为 false。

时间快照默认取 **采集时间 ≤ 目标** 的最近帧；早于首帧返回 `before_first_frame`。

档案尾部若出现序号回绕，读取截断并标 `seq_rewind_tail`。

## 历史增量与有界队列

内存队列只有 1 个最新槽 + 最多 8 条在途历史批，**不是**可靠补传。

可靠来源是磁盘档案和 `upload-cursor.json`：

- 队列满：拒绝再入队，游标不前进，下一轮从档案续传。
- 上传失败：不确认游标；进程重启后按游标继续。
- 对局 ID 变化：旧游标不并入新局。
- 档案本身缺帧或回绕：上传 `kind=gap`，查询里保留缺口。队列溢出若仍能从磁盘读到，不算丢失。

采集桥只在写配置存在时入队，不阻塞 `collect`。配置：`~/.config/sgi-war/write.env`（0600）或环境变量 `SGI_WAR_UPLOAD_URL` / `SGI_WAR_WRITE_TOKEN`。

## 私有远程同步（与 /tk 隔离）

- 写入：`POST /api/sgi-war/ingest` 头 `X-SGI-War-Write-Token`
- 读取：`GET /api/sgi-war/matches|.../latest|summary|snapshot|events|track|force|city|general|unit` 头 `X-SGI-War-Read-Token`
- 公开 `/tk` / `sgi-tk` **不得**复用这些密钥或路径

Grok / CLI 只配读取，写在受保护文件，不要写进命令参数、终端历史或聊天：

```text
umask 077
mkdir -p ~/.config/sgi-war
# 在编辑器里写入 SGI_WAR_READ_URL 与 SGI_WAR_READ_TOKEN，chmod 600
./Start-War-Query.command summary
```

测试对局必须带 `simulated` / `test_fixture`，不能覆盖真实对局。

## 只读 MCP（ChatGPT 开发者模式）

地址：`https://www.vkquant.ai/api/sgi-war/mcp`

ChatGPT 走 OAuth，**不要**也不必配置 `X-SGI-War-Read-Token`。该密钥只留在 Cloudflare Worker。写入密钥不进入 MCP。

授权口令是独立 Secret：`SGI_WAR_MCP_AUTHORIZE_SECRET`。工具全部 `readOnlyHint=true`。一次分析先取摘要，后续带同一 `snapshot_seq`。问偷袭主城用 `war_raid_plans`，不要让模型自己编路。

连接说明见同目录 `CHATGPT-MCP.md`。curl 成功不等于 ChatGPT 已接入。

## Grokbot / OpenClaw

Grokbot 不接上述 MCP。本机 OpenClaw 技能 `sgi-war` 只调 `sgi-war-query`（只读 CLI），密钥仍只在 `~/.config/sgi-war/read.env`。

```text
sh war_query/packaging/install.sh
sgi-war-query summary
```

提问规则见 `GROK_WAR_PROMPT.md` 与 `war_query/grokbot_skill/SKILL.md`。

## 停用

1. 去掉采集桥写配置或环境变量后，在对局安全结束时再重启桥。
2. 远端轮换 `SGI_WAR_WRITE_TOKEN` / `SGI_WAR_READ_TOKEN` / `SGI_WAR_MCP_AUTHORIZE_SECRET`。
3. 不要把任何密钥写进页面、日志或 `/tk`。
