# D：部队点选信息面板（默认关闭的离线候选）

工具仅用于 `prefix-fengye-shadow`、SANPK `df9b5225…`、基址 `0x400000`。
不改磁盘游戏文件、玩家侧前缀、存档或 Hub。正常 `arm_now.sh` 不加载本候选。
已完成离线机器码/字段/原生控件测试；新房中的点击、显示和 RX/lag/崩溃验收仍待进行。

## 结构与默认开关

- `p53_unit_inject.py`（复用 P51 底层）：复用原有进程绑定、洞穴和受保护站点事务；新状态文件与 P51/P52/hidden-ui 分开。
- `install` 只挂一个站点 `0x4988e3`，邮箱 `enabled=0`。不创建远程线程，不自动接收点选。
- `watch` 创建独立 Python 进程的 Win32 浮动面板，所有控件归此工具所有；以影子地图的根窗口为 owner。
- 面板“启用地图点选”按钮才续租邮箱，租约 2 秒，250ms 更新。关闭窗口/停用后停止读取，租约失效恢复原版路径。
- `--panel-fields` 默认只有 `identity`。可按顺序加 `soldiers`、`rice`、`morale`、`training`、`move_remaining`、`combat`、`unknown`，或使用 `all`。这是显示开关，不是世界属性开关。
- `combat` 使用 `unit-panel-rules/` 中五份原有纯计算源码，导入前核对 SHA。没有游戏内函数调用；网页参考字段不显示成原版攻防。
- 本地预览默认无值；只改面板的 Python 字节副本。新的源观察发生变化或重新点选时撤销预览。

## 新房操作（本轮没有执行）

在远端 shadow 目录，使用本局独立文件名。下面的 `NEW_RUN` 须替换成本局标识；不要删除旧 state 来强行重绑。

```bash
source ./_env.sh
"$WINE" "$P32" tools/p53_unit_inject.py --panel-action check \
  --state "$Z\\unit-panel-NEW_RUN.json"
"$WINE" "$P32" tools/p53_unit_inject.py --panel-action plan \
  --state "$Z\\unit-panel-NEW_RUN.json"

# 新房开始验收时，才按步骤执行；install 后点选仍关闭。
"$WINE" "$P32" tools/p53_unit_inject.py --panel-action install \
  --state "$Z\\unit-panel-NEW_RUN.json"

# watch 必须从该 Mac 的正常 GUI 会话（Terminal/LaunchServices）启动。
# SSH 直启没有图形驱动；plan/check/install/revert 可使用 SSH。
"$WINE" "$P32" tools/p53_unit_inject.py --panel-action watch \
  --state "$Z\\unit-panel-NEW_RUN.json" --panel-fields identity
```

先在面板点“启用地图点选”，单击原版地图中的部队，核对 ID/兵种/势力原始 ID/武将 ID。
原版先处理滚动条、HUD 和控件命中；只有继续进入地图的左键按下才被捕获，跳过下令分支。
不设置 `selected_unit`、不挑下一部队、不发送游戏指令。原版左键抬起保持，拖动/已有控件捕获/模态窗口时回到原版分支。
不提供双击/右键/点击卡片下令的承诺；本工具验收交互是地图单击。

每步关闭面板，再以同一 state 重开 watch，只增加一个显示元素。例如：

```bash
"$WINE" "$P32" tools/p53_unit_inject.py --panel-action watch \
  --state "$Z\\unit-panel-NEW_RUN.json" --panel-fields identity,soldiers
```

最后可使用 `--panel-fields all`。选择同格多支部队会全部列出，不默选一支；空格不会挑邻格。
没有归属过滤，敌方/电脑势力采用同一读取路径。尚未在新活局逐兵种验收。

## 本地预览

取得单一部队观察后，在面板输入框输入例如：

```text
soldiers=12000,morale=90,training=60,move_remaining=12
```

点“预览副本”，标题区域显示“本地预览”，并说明主机状态更新会覆盖、不会发送指令。
运输兵士气预览上限为 50；其余兵种（含游荡部队）士气和训练计算域为 0..100，兵力/粮 0..100000，剩余移动原始字节 0..255。
未知字段、越界值、同格多支部队不允许预览。不写单位对象、不构造合法或伪造的军令。
“恢复只读数值”立刻回到最近源观察；新的只读源数据变化也撤销预览。

## 失败与回滚

读取会双核对根、时钟、投影、链表、对象身份和选中记录。读取失败/部队移位或消失时清空旧值并提示重新点击，不重发输入。
这是有界一致性检查，不能证明世界在点击那一瞬间的原子快照。

```bash
"$WINE" "$P32" tools/p53_unit_inject.py --panel-action revert \
  --state "$Z\\unit-panel-NEW_RUN.json"
```

先关面板，再执行 revert；恢复六字节 `39 8e da 08 00 00`。候选恢复失败会尝试撤回部分站点写入并记录错误。
代码/邮箱洞穴不在活进程释放，避免旧返回地址落空；影子正常退出后由 OS 回收。
不调用 `SetEvent(netobj+0x84A4)`、不清忙标志/队列、不触碰原版玩家实例。

工具文件回滚需以本轮 `deployment.json` 的 before SHA 和备份为准，保留其他窗口随后加入的改动。
D 使用独立入口，复用 p51 的底层函数。不要用本轮备份覆盖共享 p51 的其他同期改动。

## 复现与验收

分析环境需要已有 Capstone/Unicorn；Wine 运行工具只需标准库。规则快照在 tools 内，不修改 Hub 发行目录。

```bash
python3 -m unittest -v test_p53_unit_panel
# 可用 SGI_P53_SANPK / SGI_P53_FIXTURES / SGI_P53_BRIDGE 指向已有只读证据与规则。
```

`p53_unit_watch.py --gui-smoke-fixture <fixture.json> --out <result.json>` 只创建合成面板，不发现/打开游戏，不安装补丁。
新房每放行一个元素，保留本局 PID/creation、点击/字段日志、截图、RX/lag/崩溃前后基线；出现退化先存证并撤该候选。
活局成功条件仍为用户目视正确、无错误指令、RX 持续、lag≤1且不增长、无新增崩溃。离线通过不替代这些条件。
