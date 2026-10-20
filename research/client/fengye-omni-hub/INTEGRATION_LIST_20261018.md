# 风夜操控台集成清单（新功能全部上桌，2026-10-18 晚立）

> 目的：把本轮开发的全部新能力**接进风夜操控台（omni 原生 App + Web Hub）**，一键可调用。
> 架构沿用现状：Hub 后端经 `backend/lab_remote.py`（一発式 ssh）调用实验机脚本；页面在 `native_window.py` / `static/app.js`。

## 一、能力 → 调用方式 → 状态

| # | 功能（台上按钮/区块） | 实际调用 | 状态 |
|---|---|---|---|
| 1 | **一键武装（常驻版）** | `bash ~/sgi-protocol-lab-20260915/shadow/arm_now.sh`（含 22+2 补丁硬门槛、D8 藏身、常驻 install+start、监视链、记录器） | ✅ 已实现 |
| 2 | 实验室收线 / 强制退出风夜 | `stop_shadow.sh` / `shadow_force_quit.sh` | ✅ 已有 |
| 3 | **风夜状态 + lag 曲线** | 读 `shadow/logs/lagwatch.jsonl`（每条含 host/shadow 同字段与 lag_4d6） | ✅ 日志已产出，需台面渲染 |
| 4 | **卡死/RX 早期预警** | `shadow/tools/stall_watchdog.py`（自动抓 `evidence/stall-*/` 证据 + 写 `logs/stall-watchdog.log`） | ✅ 已实现 |
| 5 | **常驻驱动状态** | `p51_shadow_inject.py --mode resident --resident-action check --state …` | ✅ |
| 6 | **上帝视角六开关**（火计/落石/陷阱/部队含伏兵/城关/生产设施） | 注入器的 C 候选站点**逐组启用/撤销**（离线已就绪、活局开关默认关） | 🟡 离线就绪 |
| 7 | **部队点选面板**（读取+本地显示） | 注入器的 D 候选（坐标命中已解） | 🟡 离线就绪 |
| 8 | **聊天检索/元数据** | `shadow/tools/chat_text_probe.py "<字符串>"`（正对照已过）；元数据=成员行时间戳+ACK 节奏 | ✅ 工具就绪 |
| 9 | **结算改值（真实生效路线）** | 数值写入工具（读—改—读回、单次、可回滚）+ 正常结算触发 | ❌ 待建（实验方案 `p54`） |
| 10 | **踢人下线（D2）** | `python3 ~/sgi-protocol-lab-20260915/d2_kick_run.py --ghost-name 风夜 --kick-target-name <X> --live-authorization <JSON> --launch` | ✅ 一键就绪 |
| 11 | 踢人下线（D3 序号线 / D7 中继面） | 下一轮开发（先只读观测） | ❌ 待开发 |

## 二、台面建议布局（新增分区）

- **「上帝视角」区**：六个独立开关（各组标注"仅显示、不放开点选/下令"）+ 一键全开/全关；
- **「部队面板」区**：一个开关（点选任意部队弹面板；含"本地改=仅显示"提示）；
- **「情报」区**：聊天字符串检索框 + 结果列表；元数据（谁与谁密谈）列表；
- **「结算改值」区**：目标对象选择 + 数值输入 + **读回确认** + "单次写入"按钮（回执里带前后值）；
- **「踢人下线」区**：目标成员下拉（从房间名册实时取）+ 授权 JSON 生成 + 「执行（一帧）」按钮 + 执行后自动拉取 host_watch 判定；
- **「监控」区**：lag 曲线（折线）+ 冻结预警状态 + 常驻驱动状态（owner/in_flight/started/returned 计数）。

## 三、实现顺序（建议）

1. **监控区**（纯读日志，零风险：lag/预警/常驻状态）；
2. **踢人下线区**（包一层 `d2_kick_run.py`，按钮 = 生成授权 + 拉起 + 回执）；
3. **情报区**（聊天检索 + 元数据）；
4. **上帝视角/部队面板区**（等活局验收通过后放开开关）；
5. **结算改值区**（先出工具，再上桌）。

## 四、红线状态

用户已于 2026-10-18 解除全部旧限制；本清单不再包含政策红线条款，仅保留工程纪律（备份、可回滚、留证据、单发不重试）。

---

## 五、接线收尾说明（2026-10-18 晚，F1 后端已完成）

**已完成**：`backend/lab_tools.py`（6 个函数，全部走既有 `lab_remote` 一発 ssh；除 `session_op` 外只读）。
- 实测：`lag_tail` 3 行 ✓、`chat_search("丁满")` 命中 6 处 ✓（单元测试 5 项全过：脚本生成/解析/confirm 门）。
- 注意：`lab_remote` 的 host 必须用 **Hub 配置里的完整 `ssh_target`**（含用户名，如 `vkquant@fd7a:...`），否则 `~` 解析到错误 home（本轮踩过）。

**剩余接线（照抄即可）**：
1. `backend/server.py` `do_GET` 加 4 条只读路由（并与 web hub 的 server.py **同步同一份字节**，保持钉子测试）：
   ```python
   elif path == '/api/lab/resident':
       self.respond(json.dumps(lab_tools.resident_check(cfg['ssh_target']), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
   elif path == '/api/lab/lag':
       self.respond(json.dumps(lab_tools.lag_tail(cfg['ssh_target'], 60), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
   elif path == '/api/lab/stall':
       self.respond(json.dumps(lab_tools.stall_tail(cfg['ssh_target'], 40), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
   elif path.startswith('/api/lab/chat'):
       q = parse_qs(urlsplit(self.path).query).get('q', [''])[0]
       self.respond(json.dumps(lab_tools.chat_search(cfg['ssh_target'], q), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
   ```
2. `do_POST` 加一条带确认的 `/api/lab/sessionop`（body 需 `{"confirm": true, "target": "<成员名>"}`），转 `lab_tools.session_op(...)`；
   UI 必须弹确认框（写明"一帧、不可重试、目标会掉线"）。
3. UI（`native_window.py` + `static/app.js`）按本文二节分区铺开，数据源即上述 5 个端点；
   上帝视角/部队面板两组开关沿用已完成的离线开关入口（默认全关）。
4. 验收：Hub 既有测试（原生 30+ / web 50+）全绿；`.app` 重建 + dist；只改本仓库与实验机。
