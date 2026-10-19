# 多线3线路及 VKQUANT-COM 房间地址：2026-10-13

## 实测结果

- VKQUANT-COM 房主 **丁满**；房间 **SGZWLB**；游戏地址 **10.82.171.21:7777**。
- 游戏地址是平台虚拟网络中的 10/8 私有地址，不是房主公网 IP。主机标识 **173189909 / 0x0A52AB15**，依此前已审核 `NetMsg_GetIPString` 的高字节在前格式解析。
- 两次独立只读读取同一 Windows 游戏进程 PID **732** 一致；`is_host=1`、当前连接成员数1、搜索门控 `8410=1 / 8414=1`。SANPK SHA256 `df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea`；KOEINM SHA256 `629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841`。
- 窗口证据显示建房设置画面，包含“开始游戏”按钮；不将“客户端已启动”误记为对局已经开始。

## 多线3实时目录及独立搜索

使用现有专用小号风夜，单次登录、单次入线拿授权、随即离开大厅名单，复用原转发 DLL 做三次 SearchSession；无 OpenSession 加入对局。没有重新启停主号、没有强制登录。

实时服务器目录确认：

| 线路 | 线路编号 | 目录转发地址 |
| --- | --- | --- |
| 电信1（备用） | 1000 | 61.147.99.233:9008 |
| 多线2（主线） | 1001 | server 空值（客户端回落登录服 121.41.166.208）:9151 |
| 多线3（备用） | 1002 | 36.151.147.251:29100 |
| 香港中转2（海外） | 1003 | 38.175.194.244:9171 |

`1002` 的授权回执成功，中继 `start_rc=0 / relay_registered=true`。三次搜索均为 **unconfirmed_empty**，未得到房间响应；不能翻译为无房或已经开局，也没有证明房间地址可从搜索接口取得或已能直接连接。

上述房间 IP 来自房主游戏的只读网络成员槽，**不是 /tk 或独立搜房返回值**。线路3由用户说明；尝试从大厅树选中项独立读取线路失败（ReadProcessMemory 地址无效），保留失败回执，不将其当作线路确认。未进一步探测 IP/端口。

## /tk 限制

代码至少有三处固定为主线：

- `resident_session.py`：`TARGET_ROOM_SUBSTR="多线2"`。
- `loader_resident.py`：只允许 `game_id==1001 and room_id==1001`。
- `sgi_bot_client.py`：结果固定标注多线2及线路编号1001。

因此只改页面标题不能让 /tk 同时搜多线3。本轮只做研究副本，未修改 /tk、已安装 Hub 或上线采集策略。检查时本机 resident 状态停在 2026-10-10，上传调度仍在运行但最新查询为 `collector_unavailable`；这是额外的采集停止问题，不能把旧状态当实时房间列表。

## 证据及边界

- `result.json`：线路目录、授权和三次搜索回执，无凭据及授权 token。
- `host-read.jsonl` / `host-read-repeat.jsonl`：两次只读游戏地址读取。
- `host-read-first-attempt.jsonl`：旧脚本沿用历史房主 kwankwan 导致绑定断言失败的首轮记录；之后按当前大厅账号绑定丁满。
- `selected-line*.jsonl`：未成功的选中线路读取，stderr 明确保留。
- `query_line3.py` / `loader_line3.py` / `koeinm_probe.py`：仅本研究目录的临时实验副本；主脚本不变。
- 静态语义复用 `../host-ip-check-20261006/RESULT.md` 及其中 NetMsg_GetHostID、NetMsg_GetIPString 和搜索记录证据；本次未重复反汇编。

无游戏内存写入、EXE/DLL 修改、对局操作、存档覆盖、网络扫描或新增常驻服务。研究副本也保存到 VKQUANT-COM 的 `~/sgi-protocol-lab-20260915/evidence/multiline3-20261013/`；本地汇总为完整证据。
