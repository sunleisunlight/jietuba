# 任务1报告：阻塞，未通过

2026-10-19；候选2.8.2；工作路径/分支以STATE.md为准。

## 已实现

- 用共享用户级锁+本地socket确认唤起替代启动时杀旧进程。旧版无协议时提示用户先安全退出；不杀PID、不打断现有编辑/录制。
- Mac普通启动显示可操作设置入口；--autostart静默；Dock reopen扩展Qt已有delegate而不替换其退出/菜单处理；优先恢复活动截图或模态窗口。
- 自启注册迁入平台backend；Mac plistlib转义特殊路径、原子登记，保存失败明确反馈；Windows保留HKCU Run注册机制。
- 窗口图标经platform factory；Windows保留LoadImage/WM_SETICON，Mac不再调用windll。
- 截图权限检查失败立即停止，未授权与未知状态区分；错误对话框参数修正；首次启动失败不再无条件标记已运行。
- 修复GIF扩展缺失Clang availability runtime导致import失败；打包前增加原生import前置校验。
- CI增加显式任务1定向门禁（不改变默认全量流程），测试进程有超时、失败仍记失败；exe来源清单跟随模型已内置的一文件产物。
- graphify用于定位启动/设置调用链，所有改动以当前源文件核验。构建依旧复用Windows品牌资源。未编辑README用户草稿。

## 功能盘点与验证

矩阵744行：33条任务1验收操作 + 667条源码候选入口/操作绑定/设置 + 29条controller动态菜单 + 7条Qt编辑菜单 + 8条Windows2.8.0新增/变更操作。状态没有任何「对齐已实测」或「原生等效已验证」。候选项不能当作全部独立用户功能已穷尽；Windows可见性独立复核仍未完成。

统计以STATE.md为准，旧统计669项未检查已被新增清单覆盖。

最新相关Python回归188通过/6 Windows专属跳过；本轮 QtNetwork 契约修复后针对性 macOS 测试42通过/2跳过；此前Rust19通过（Rust源码未再改变）；全main lint通过。Windows x64/ARM64 CI39168681792各144项定向结果为137通过/7平台跳过/0失败，并完成真实 exe；随后发现 Windows whitelist 仍漏 QtNetwork DLL/pyd，已在 c7e78a3 修复并触发 CI39169825988复核。详见TEST_EVIDENCE.md，单元/Mock/原生delegate调用不等于真实App操作。

## 实际安装与数据保护

旧PID59837已退出并备份。当前 `/Applications/积磊截图.app` 已替换为本轮2.8.2候选，旧版及上一轮候选保存在 `dist/task1-install-backup-4BgqPj/`；没有强杀、没有清空真实配置、历史、剪贴板，自启和TCC均未修改。修复后通过终端启动的候选进程可持续运行并打开设置页；Finder三轮双击、重复打开、退出重开和Dock/菜单栏回归仍待 action-time 确认后执行。Computer Use读取旧App超时是此前记录，不作为最新候选证据。

## 构建/交付

新App构建及Apple Development签名成功，DMG校验成功。用户提供桌面凭据后更新签名成功并通过固定公钥验证；暂存四文件见STATE.md，未封版或新增到release。现有release旧包原地保留。未公证、未生产发布、未合回main。

最新运行源码Commit `c7e78a3`（完整 SHA 见 Git）已推送并核对远端；正式Tag未创建。Windows定向CI39170509042的两个架构测试/构建成功，实际x64包体已核对QtNetwork和comtypes；该跑次Mac job及全量39169825988失败情况见证据J。最新App主程序hash见证据I；旧包不能代表当前候选。

## 本轮继续执行新增结果

- Windows正式软件基线已更正为2.8.0：下载exe并核对清单hash、字节数、包内版本。Tag源码7c0d289；main仍为2.7.0，精确构建SHA证明仍缺。
- 新增剪贴板搜索/OCR索引/预览尺寸归任务3安全吸收；本轮没有盲目合并，也没有提前执行任务3。
- Windows原生失败根因：WScript快捷方式链路在英文区域设置下损坏中文路径。复用既有comtypes的IShellLinkW，经生命周期factory供品牌迁移和欢迎向导共用；原生测试回读实际目标、工作目录、参数、图标。
- 修复Windows打包排除QtNetwork会使新增单实例模块无法导入的问题，并补打包契约断言。Mac重新构建，不以旧包代表新代码。

## 最小解除条件

1. 更新签名阻塞已解除，凭据路径见AGENTS.md；不要再要求用户重复提供。Apple Developer ID及公证仍缺，不能把updater密钥当Apple证书。
2. 旧App已退出并备份，此项已解除，无需用户重复退出。
3. Windows定向测试与真实exe构建已取得精确候选SHA证据；继续Mac正式入口验证，当前导航自动化只切换选中态、内容页不切换，需要先区分工具限制和应用故障。
4. 系统设置已只读确认辅助功能、输入监控均开启；未撤销或重置。用户已同意可恢复自启测试，尚未执行。登录测试、最低系统、额外显示器缺环境必须继续单列。App内授权恢复仍未通过。

下一步仍为「继续执行任务1」，不是任务2。任务2～5只登记范围，没有提前执行。
