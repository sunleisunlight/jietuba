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

矩阵700行：33条任务1验收操作 + 667条源码候选入口/操作绑定/设置。状态没有任何「对齐已实测」或「原生等效已验证」。候选项不能当作全部独立用户功能已穷尽；Windows可见性和动态入口独立复核仍未完成。

统计：未检查669、已实现待实测21、环境阻塞10、测试失败0、原生等效已验证0、对齐已实测0。

相关Python回归去重187通过/5 Windows专属跳过；Rust19通过；全main lint通过。详见TEST_EVIDENCE.md，单元/Mock/原生delegate调用不等于真实App操作。

## 实际安装与数据保护

旧安装仍为 `/Applications/积磊截图.app` v2.8.1，PID59837。Computer Use读取旧App两次超时；只读sample显示正常事件循环等待，不能断言挂死。没有强杀、没有替换安装；新App仅在dist。没有清空真实配置、历史、剪贴板，自启和TCC均未修改。未创建安装备份，因为尚未替换。

## 构建/交付

新App构建及Apple Development签名成功，DMG校验成功。更新签名因缺少可用口令失败；暂存三文件见STATE.md，不是完整四件套。现有release旧包原地保留。未公证、未生产发布、未合回main。

源码Commit c5ac3985a90a75d89a8faa2aabcebf6d4fe34372已推送并核对远端；正式Tag未创建。Windows定向CI run39166063824已启动，未完成时不能称Windows门禁通过。最终App及archive/DMG同源哈希见证据E。

## 最小解除条件

1. 安全签名入口注入 `JILEI_TAURI_KEY_PASSWORD` 或 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`；不把口令贴到聊天、日志或仓库。
2. 用户保存旧App的未完成工作并正常退出（若正常退出也不可用，先由用户决定如何结束，Agent不强杀）。
3. Windows定向测试与真实exe构建取得精确候选SHA证据后，继续本轮Mac安装/正式入口验证。
4. 真实权限变更与可恢复自启开关测试需用户确认；登录测试、最低系统、额外显示器缺环境必须继续单列。

下一步仍为「继续执行任务1」，不是任务2。任务2～5只登记范围，没有提前执行。
