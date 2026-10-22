# ASTRA_HANDOFF_PACKAGE

## 合同与工作区
继续完成 Grokbot 独立小号监控软件包。仓库 `/Users/vk/Documents/Coding/三国志internet`。无可用 HEAD。未重置既有未提交文件。

## 当前 Phase 目标
独立 prefix、可安装软件包、OpenClaw 适配、离线测试；凭据到位后做真机闭环。

## 原始 Acceptance Criteria
AC-01 到 AC-10 见本合同。真实登录/30 分钟/列表三人核对依赖小号凭据。

## 已完成工作
- 独立 Wine prefix `prefix-monitor`（wineboot 新注册表，未复制主号 UserConfig/存档/崩溃记录）
- SANPK SHA256 与主号一致；监控 UserConfig 空用户名/空密码；UDP 4578
- 主号 SANPK PID 49801、启动时间 2026-09-14 23:52:12 未变
- 凭据入口 `sgi-room-monitor creds-set`（钥匙串优先）
- 软件包 0.1.1 已安装、升级后配置保留
- OpenClaw Telegram 私聊测试消息送达（`ok: true`）
- 单元测试：monitor 21、bridge 225

## 修改文件
`room_monitor/` 全套；`bridge/room_instance.py`、`room_list_probe.py`、`room_list_reader.py`；`app/room_watch.py`（上轮多实例，本轮沿用）

## 已尝试方案
wineboot 首次因缺少 DYLD_FALLBACK_LIBRARY_PATH 失败；补上 runtime lib 后成功。未对主号 wineserver 执行 -k。未启动监控大厅，避免 UDP/单实例风险。

## 测试结果
见 EVIDENCE.md。模拟/回放通过。真机列表刷新未做。

## 失败证据
无工程失败。闭环缺小号凭据。

## 当前 root cause 假设
小号 vinceost 在其他会话已在线。本机强制登录勾选未能踢掉旧会话。

## workers 之间是否存在结论冲突
无。总指挥直接实现。

## 尚未解决的问题
小号登录、进入多线2、到达游戏选择、30 分钟刷新、三次界面核对。

## 当前 architecture 决策
采集端与 Grokbot 同机 VKQUANT.AI。发送只走 OpenClaw Telegram allowlist DM。Grok Bot.app 是桌面壳，不改包体。监控大厅若启动必须用独立 prefix + UDP 4578。

## 推荐 Astra 裁决的问题
无战略分歧。只需用户完成本机凭据输入。

## Grok 推荐的下一步
用户在监控登录窗（标题「三国志Internet对战平台-用户登录」，不是主号）勾选强制登录并点登录，或先在另一台机器退出 vinceost。成功后继续进多线2 / 启动游戏 / 列表刷新。不必上传软件包到 Grokbot。

## 关键代码 / diff / log 路径
- 安装：`~/Library/Application Support/SGI-Room-Monitor/opt`
- 包：`~/Library/Application Support/SGI-Room-Monitor/sgi-room-monitor-0.1.1.tgz`
- prefix 报告：`~/Library/Application Support/SGI-Room-Monitor/prefix-report.json`
- 证据：`room_monitor/EVIDENCE.md`

## 是否存在外部副作用
创建了 `prefix-monitor`。向用户 Telegram 私聊发送了标注【监控测试】的通道验证。未操作主号、未改 EXE、未覆盖存档。
