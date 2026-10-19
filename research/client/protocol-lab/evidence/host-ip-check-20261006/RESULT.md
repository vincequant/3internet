# kwankwan 房间 IP 只读核验 — 2026-10-06

用户表示在电信1（备用）建房，要求查询 IP。本次直接由当前 GPT 执行，无委派。

## 实测结果

在 VKQUANT-COM 已运行的 prefix-sikarugir10 中，确认大厅当前用户为 kwankwan、SANPK 位于建房设置界面。两次独立只读读取同一游戏进程（Wine PID 664），核验 KOEINM SHA256 后，以 OpenProcess(0x410) + ReadProcessMemory 读取已静态定位的字段：

- 房间名 SGZWLB；房主名 kwankwan；is_host = 1。
- 主机标识 176202538（0x0A80A32A）；按原 DLL 的 NetMsg_GetIPString 高字节在前解析为 **10.128.163.42**。
- 游戏网络端口 7777、应用标识 78731、上限 8。
- 地址属于 10.0.0.0/8 私有地址范围；不是房主公网 IP。结合平台 NetHook 通道，作为平台内网/虚拟地址理解，未测公网直接可达性。
- 用户提供的线路为电信1（备用），本次未从大厅选中树节点独立证明线路名称。

## 编号解释与证据

KOEINM NetMsg_GetHostID -> 0x10004c80：当 is_host 为真，返回网络对象 +0x43b8 指针所指首个用户槽的首 DWORD。本次从该槽同时读出 kwankwan 与 176202538。

NetMsg_GetIPString（0x100022d0）按高字节到低字节格式化 IPv4。

搜索响应 0x10007d30 调用 0x10008a80（gethostname/gethostbyname 首地址）作为响应首四字节；SearchSession（0x10001870）将该字段通过 ntohl 放入 80 字节记录首 DWORD。TK 当前将此值存为十进制 id。因此应将现有编号作为带来源证据的 IPv4 地址编码研究，而不是声称它绝不包含地址。当前房间未从独立搜房响应中捕获，不能将本机读取冒充 TK 已查到该房间。

## 未成功的查询与限制

- 独立临时副本尝试登录小号并选择电信1（备用），连接被服务器重置（ConnectionResetError），未拿到线路列表，未重试或强制登录。
- 在既有主号 prefix 内运行独立 Koeinm 查询，返回 unconfirmed_empty、Windows 10，未收到房间响应；不能说该线路无房。未更改兼容设置、现有 TK 配置或凭据。
- 无加入、开局、关闭游戏、运行内存写入、端口或网段扫描；无存档或 EXE 修改。
- 本次已确认房主客户端的游戏地址，未确认公网 IP、第三方凭记录获取本房地址、地址的直接连通性、旁观身份或开局后状态同步；尚不能凭此打开 Hub 观战。

## 文件

- host-memory-ip.jsonl / host-memory-ip-repeat.jsonl：两次原始脱敏读取结果。
- host-live-query.jsonl：窗口与独立搜房回执。
- query-1.json：协议登录失败回执。
- koeinm-*.txt：静态反汇编依据。
- read_host_ip_20261006.py 及临时查询脚本：研究副本，不覆盖已安装 Hub/TK 程序，不发布到其他平台。
