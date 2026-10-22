# M4 / SanguoInternet 专用更新 0.2

默认目标：Apple M4、macOS26.4、CrossOver26.3，win10_64 Bottle `SanguoInternet`。平台 `C:\sgi\run-3.5\SANGUO.exe` 拉起实际游戏 `C:\sgi\run-3.5\3I\SANPK.exe`。本包不会自动启动平台或新游戏。

先运行游戏并进入地图，再在Mac终端分别运行：

```bash
bash "/实际解压路径/SGI-Hub-CrossOver-M4-0.2/Start-Bridge-Mac.command"
bash "/实际解压路径/SGI-Hub-CrossOver-M4-0.2/Start-Mac.command"
```

第一个命令保持运行，在另一个终端运行第二个。Bridge脚本默认选择SanguoInternet，显式通过CrossOver自带wine启动Windows Python。可用SGI_BOTTLE覆盖名称；不创建、不修改Bottle。若命令启动兼容性不符，回到CrossOver选中同一Bottle，运行包内bridge/Start-Bridge.bat。

不调用winedbg、DebugActiveProcess或Mac task_for_pid，不关闭SIP，不注入或写游戏内存。每次启动重新枚举PID并扫描GameCore，禁用旧binding.json缓存，运行中只沿当前验证过的指针链读取。游戏重启/读档后建议重启Bridge。固定PE布局仍受可执行文件SHA256检查保护；每次从进程模块列表取得映像基址，按PE重定位差调整类型标记；查询失败即停止，不使用历史基址。

命令行形式依据：https://www.codeweavers.com/support/docs/crossover-mac/index 。这些脚本尚未在你的Mac实际执行。Windows Python在M4的CrossOver兼容性仍属于首测事项；不能因为winedbg崩溃推断普通ReadProcessMemory也一定失败或一定成功。

---

# 测试包使用说明

本包是可移植源码＋游戏素材＋Windows只读采集桥，不是已在Mac验证或签名的独立.app/DMG，也不包含SANPK游戏、账号、存档或Windows旧局快照。仅供你自己的已安装游戏使用。它辅助查看/决策，不会自动操作游戏或训练AI。

## 首次运行
1. 将整个ZIP复制到Mac后解压，保持目录完整。Mac端安装 python.org 提供的 macOS Python 3.12（带Tk）；Intel或Apple Silicon需选择适合本机的安装包。
2. 在 CrossOver 中打开原游戏所在Bottle，进入可操作地图。当前只支持 SHA256 为 c06ec3aa9c2b539e4111b53c57bed3717a2c0c73f3145aac4d55f66b2abb26cc 的 SANPK.exe 3.5。另一个版本不会自动套偏移。
3. 在 CrossOver 中选中 **同一Bottle** → 运行命令 → 浏览到本包 bridge/Start-Bridge.bat 并运行。若不能直接运行BAT，选择该Bottle内 cmd.exe，参数为 `/c "Z:\Users\你的用户名\Downloads\SGI-Hub-CrossOver-M4-0.2\bridge\Start-Bridge.bat"`（按实际路径修改）。不要双击到其他Bottle。
4. 采集桥会自动查找该Bottle中的唯一 SANPK 进程。保持命令窗口打开。只监听本机 127.0.0.1:8769，不开启局域网服务。Mac浏览器访问 http://127.0.0.1:8769/health 应显示 fresh:true；失败信息在 error 字段。
5. 在Mac终端执行 `bash "/实际路径/SGI-Hub-CrossOver-M4-0.2/Start-Mac.command"`。首次会在包内建立.venv并从PyPI安装Pillow。亦可双击.command；若执行位未保留，用上述bash命令。
6. Hub连通后应出现22势力、当前武将、手牌等真实记录。未连接时不会冒用Windows旧快照显示“实时”。本包我军槽位仍按原项目为11（宋）；首次请核对确实是宋，否则不要使用我方专用预测。

## 验证重点
- 此机未有Mac/CrossOver，未验证它的进程枚举、ReadProcessMemory、x64 Windows Python启动或本机回环网络互通；它们都是首测关卡。
- 如果Bottle不支持附带的x64 Windows Python，或游戏并非同一版本，请保留错误，不要替换DLL、关闭安全防护或强行调用错误偏移。
- 建议先对照你看得到的金米、兵力、五张手牌，再观察一次你手动进行的操作后Hub是否更新。没有通过前不要依据预测作重要决策。
- 地图原版底图已附带。旧Windows局的彩色边界未移植为当前事实；新进程的势力色未校准时为中性色。地图尺寸仍为本项目101×202剧本，其他地图尚不支持。
- 训练范围、网站参考收益及技能匹配的既有限制保留；部队尚未完成Mac实战核验。

## 生成Mac应用
确认源码启动正常后，在Mac运行 `bash Build-App-on-Mac.command`。脚本用本机Python/PyInstaller生成未签名的 dist/SGI-Hub.app，适用于所用Python架构，不承诺跨架构通用。该.app仍需CrossOver采集桥；不能直接读取Wine进程的Mac内存代替桥。

## 排错与停止
- Mac日志：logs/mac-last-run.log。CrossOver端保留控制台错误，截图或复制 error 字段供排查。
- fresh:false 时停止相信旧数据；读档或重启游戏后重新启动采集桥，重新发现PID与基址。
- 停止Hub：关闭Hub窗口；停止桥：关闭其控制台。它不会关闭游戏。
- 不操作公共真人对局；全知读取仅用于你自己的全电脑研究局。

## 打包内容
app为跨平台Hub，assets为你本机游戏的小地图/卡牌资源；bridge含只读Python源码和从python.org下载的Windows嵌入式Python3.12.10。Windows运行时源URL、SHA256在WINDOWS_RUNTIME.json，Python许可在bridge/python/LICENSE.txt。文件清单及SHA256见MANIFEST.json。

本次Windows受限执行环境的模块枚举实测返回错误5（拒绝访问），因此0.2的端到端动态重定位尚未验证通过。程序会打印具体系统错误并停止，不降级到历史地址。此前0.1的采集结果不能代替这项验证。
