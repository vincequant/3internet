# P52 离线候选：信息栏、聊天、全图

本轮代码已经编译/模拟；**尚未在活局启用**，正常 `arm_now.sh` 不调用 UI 模式。新房先验收 P51 常驻驱动，再按下列顺序逐元素放行。仅用于 `prefix-fengye-shadow`，磁盘游戏文件保持原 SHA。

## 只读检查

在远端 `~/sgi-protocol-lab-20260915/shadow/` 下：

```bash
source ./_env.sh
"$WINE" "$P32" tools/p51_shadow_inject.py --mode ui --ui-action check \
  --state "$Z\\ui-state-p52.json"
"$WINE" "$P32" tools/p52_panel_snapshot.py --bridge "$Z\\bridge"
```

`check` 不分配洞穴、不改站点；`plan` 也不写进程。新进程使用新的 state 文件，保留旧文件作为证据，不使用 `--force`。

## A：逐项启用与回滚

`panel-create` 必须在新进程切入对局、原生 `0x4870a4` 创建面板前安装。它创建七条原生数字控件和卡牌控件，数据从当前借用席位的真实势力取得。若创建时席位未知/势力缺失会安全跳过；这个候选没有对既存空面板强制重建功能，不能在旧界面里安装后就宣称已显示。

```bash
# 以下仅为下一轮操作说明；本轮没有执行 install。
"$WINE" "$P32" tools/p51_shadow_inject.py --mode ui --ui-action plan \
  --ui-element panel-create --state "$Z\\ui-state-p52.json"
"$WINE" "$P32" tools/p51_shadow_inject.py --mode ui --ui-action install \
  --ui-element panel-create --state "$Z\\ui-state-p52.json"
```

随后分别启用 `stat-12c`（信望）、`stat-12d`（支配率）、`stat-12e`（金）、`stat-12f`（米）、`stat-130`（步兵）、`stat-131`（骑兵）、`stat-132`（弓兵），最后 `cards-init` / `cards-update`。每次只改一个入口，记录字段快照与截图。

```bash
"$WINE" "$P32" tools/p51_shadow_inject.py --mode ui --ui-action revert \
  --ui-element stat-12e --state "$Z\\ui-state-p52.json"
```

回滚恢复 P51 封印字节，**不是还原原版循环**。撤销 `panel-create` 只影响后续创建，已经构造的原生控件由原版窗口析构回收；不在活局直接删控件。洞穴直到进程退出才释放，避免旧栈返回到已释放地址。重启影子会自然清除所有运行时补丁（重启按原有收线纪律执行）。

## B：盟军私聊是定向投递

原版 `0x499505` 只列出双向关系 3 的其他活动真人行；发送循环 `0x42b964` 按选中成员 ID 调用 `ChatTo`。DLL `0x5e02` 只投递给指定 ID。风夜借用 `my_slot` 不会改变自己的网络 ID，因此无法收到别的盟友之间的私聊。

原版 `0x4993e2` 对已收到的私聊会保留发言者名/正文，并传入私聊标志。Unicorn 已覆盖该分支及单次释放，不需要解封数值刷新族。不提供伪造 ID、修改他人收件人、主机改造或复制未收到消息的实现。

## C：仅渲染调用点的候选

逐个候选：`map-tiles`、`map-unit-sight`、`map-unit-detail`、`map-city-detail`、`map-city-skin`、`map-site-detail`、`map-marker-detail`。这些点在颜色/单位/城池/设施/标记的绘制路径内；不改共享 `0x468662/0x4686c7/0x468724`、不改 `lord+0x89` 位图、不改同步数据。

启用与回滚使用同一 `--ui-action install|revert --ui-element ...`。全图是否还有缓存、低缩放或其他图层过滤需要活局目视检查；离线分支测试不等于全图验收成功。切换后用正常重绘/平移检查，工具本身不调用网络 API、不同步唤醒窗口。

## 每个元素的活局判据

保留本局 PID/creation/核心/势力/席位绑定；先取得有效两端 lag 样本与 RX、崩溃基线。每次放行后继续观察多个真实推进回合：lag≤1 且不增长、RX 无长静默、崩溃记录无新增，并由用户目视核对。基线本来已断流/缺主机时不开始试验，也不记为成功。

任何新退化先冻结日志和字段快照，回滚刚放行的那一项；不得调用 SetEvent(netobj+0x84a4)、清忙标志/接收队列、整族 unseal，或自动收线/重武装。

离线复现：`python -m unittest -v test_p52_shadow_ui test_p51_shadow_resident`。需要 Unicorn；`SGI_P52_SANPK` 可指定本机已有的只读 df9b5225 原档。UI/DLL 系统接口在测试中使用桩，不是图形或网络实测。
