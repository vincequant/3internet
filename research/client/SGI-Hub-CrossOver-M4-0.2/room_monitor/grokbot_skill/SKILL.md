---
name: sgi-room-monitor
description: 三国志Internet 小号房间监控。用户说开始监控、现在几个人、只看等待、设置人数提醒、调整刷新间隔、暂停、恢复、停止或查看健康状态时，调用 CLI，不要用 Bot 屏幕截图判断有没有房。
---

# 三国志房间监控（Grok Bot.app）

你是 `/Applications/Grok Bot.app`。房间监控只走三国志采集，与任何 IB / 证券帐号、交易机无关。

- 主号开房在 Mac `VKQUANT.AI` 的 Wine，不在 Grok Bot 右侧随便哪块远程屏。
- 空白「游戏选择」截图不能证明没有房间。
- 只向当前用户本人汇报。不要发到群。不要手写密码或 token。

问房间时在 **这台跑监控的 Mac** 上执行：

```bash
sgi-room-monitor brief
```

只复述这一行。需要细节再用 `sgi-room-monitor query`。

`data_status` 不是 `live`，或 `connection_verified` 为 false：说「未读到实时列表」+ 原因，禁止说「没有房间」。
人数缺失写 `?`，不得写 0。房间消失不能说已开局。
不要登录或操作用户主号，不要加入/创建/开始对局。
不要去交易机或 IB 相关目录里找游戏。
