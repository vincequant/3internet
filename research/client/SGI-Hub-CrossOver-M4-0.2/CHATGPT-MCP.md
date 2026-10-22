# ChatGPT 只读战局 MCP

数据与 Grok CLI / HTTP API 相同。MCP 只读，不另建采集。Grokbot 不走本文件，见 `war_query/grokbot_skill/SKILL.md`。

## 连接

1. ChatGPT 网页：Settings → Security and login → Developer mode。
2. Plugins → 加号 → 创建 developer-mode app。
3. MCP 地址：`https://www.vkquant.ai/api/sgi-war/mcp`
4. 传输：Streamable HTTP（也接受 SSE）。
5. 鉴权：OAuth。授权页输入本机保存的授权口令（Cloudflare secret 名 `SGI_WAR_MCP_AUTHORIZE_SECRET`）。不要把战局读写 token 填进 ChatGPT。
6. 对话里打开 Developer mode，只选用此 app。先问当前战局摘要，再讨论招将或宣战。

## 工具

| 工具 | 用途 |
|---|---|
| war_matches | 已上传复盘列表。问「有哪些复盘 / 选哪一局」时先用这个 |
| war_brief | 单局短报；返回里带 `available_reviews`，旧会话即使没刷新到 `war_matches` 也能列出全部玩家局 |
| war_current_summary | 对局、身份、采集时间、摘要；记下 `snapshot_seq` |
| war_raid_plans | 偷袭主城：出兵城、落点、集结、回合、是否容易被发现 |
| war_city_detail / war_general_detail | 招将与城池 |
| war_force_detail / war_unit_detail | 兵力与部署 |
| war_events | 分页事件 |
| war_track | 已观察轨迹 |
| war_snapshot | 历史快照，不取未来帧 |

提问规则见 `GROK_WAR_PROMPT.md`。网页问答也适用：先读最新已上传数据，后续固定同一快照。

## 限制

这里的实时是提问时查询已上传数据，不是 ChatGPT 盯着每一帧。回答必须标观测时间。
curl 或本地 `--demo` 不能代替 ChatGPT 网页工具调用验收。
