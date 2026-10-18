# Mac 对齐任务状态

更新：2026-10-19（Asia/Shanghai）。任务1 **阻塞，未通过**。不要自动执行任务2～5。

## 唯一接续目录

- 工作目录：`/Users/sunlei/codex/jietuba`
- 分支：`fix/macos-native-parity`。不合回 main。
- Windows 最新正式源码Tag：v2.8.0 / `7c0d289475ee630a4102f2b7e36b9aa8e49bb54c`，2026-10-19；main仍停在v2.7.0/a26380e。
- Windows 正式软件基线：已下载公开清单2.8.0的exe，SHA256/大小与清单一致，包内APP_VERSION=2.8.0；精确exe→源码SHA构建证明仍缺。旧矩阵保留a26380e行号，增量WIN280-1～8归任务3，候选Mac尚未吸收该提交。见 BASELINE.md。
- Mac 候选版本：2.8.2（尚未封版）；最新源码提交 `c7e78a3`（QtNetwork 打包修复，已推送origin并核验）。候选 App 主程序 SHA256=`cb6e449aeb5d0b6535b7ea419a9dcd15cc2ee3370d0a258e250e4b74bff21879`。
- 原有 README.md / README_zh-CN.md / README_JA.md 草稿和 graphify-out-main/ 保留，未纳入本任务提交。
- 旧 worktree `/Users/sunlei/codex/jietuba-unified`、`/Users/sunlei/codex/jietuba-macos` 未改动；不可从旧分支覆盖本轮修复。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| 1 | 阻塞 | 代码、回归和真实Mac构建已完成一轮；签名口令、Windows门禁、安装App实测未闭环 |
| 2 | 阻塞 | 尚未执行，等待任务1与用户调用 |
| 3 | 阻塞 | 尚未执行，等待前置任务与用户调用 |
| 4 | 阻塞 | 尚未执行，等待前置任务与用户调用 |
| 5 | 阻塞 | 尚未执行，等待前置任务与用户调用 |

## 当前交付与阻塞

- `.app`：`/Applications/积磊截图.app`（2.8.2，arm64，Apple Development；构建源 `c7e78a3`）。资源、原生依赖、签名校验通过；Gatekeeper 拒绝，未公证。修复后终端启动进程持续运行并可读设置 AX 树；Finder/Dock真实循环尚未完成。
- 最新暂存目录：`/Users/sunlei/codex/jietuba/dist/macos-release-sz88t8x3/`，有 app.tar.gz、DMG、更新说明；**缺少有效 .sig，未形成四件套**。此前u4oz6qdm/i22urk_u/ujgi7u90均为旧调试迭代，保留但不是最新候选，勿交付。dist/积磊截图.app 已恢复为与安装包相同的副本。
- `dist/release/` 的 v2.8.1 四文件未删除/覆盖/移动；没有把半套2.8.2放入 release。
- 签名使用已有私钥路径；当前会话未注入口令，单次空口令尝试返回 Wrong password。停止尝试，不读取密码/私钥、不猜测凭据。
- 旧安装原PID59837已退出并由 `dist/task1-install-backup-4BgqPj/积磊截图-v2.8.1-installed.zip` 保留；上一轮候选也在同目录。替换未清理用户数据。修复后 Finder 定位可见2.8.2，但实际三轮双击/重复打开/退出重开仍待确认；此前AX超时不能作为新候选运行证据。
- 自启开关、权限撤销/授权、真实首次配置和实际重新登录尚未测试；未改变用户真实TCC或LaunchAgent。
- Windows候选CI：[39166063824](https://github.com/sunleisunlight/jietuba/actions/runs/39166063824)及两次诊断跑次均在中文桌面快捷方式迁移失败；98a1cbc改用原生IShellLinkW。39168681792 的 x64/ARM64 测试和构建虽成功，但归档复核发现 QtNetwork whitelist 漏 DLL/pyd；c7e78a3 已修复，最新复核 CI：[39169825988](https://github.com/sunleisunlight/jietuba/actions/runs/39169825988)，运行中。
- 正式Tag `v2.8.2` 未创建，四件套/真实App验收未闭环，不冒称正式发布完成。没有生产发布、没有合回main。

## 接续顺序

1. 核验本文件记录与当前Git状态；查看候选CI的确切SHA结果。
2. 查看 c7e78a3 的完整CI39169825988及定向CI39170509042（后者明确 parity_task1=true）；取得exe并核对QtNetwork.pyd、Qt6Network.dll及PYZ内comtypes.shelllink/persist，不能只信构建退出0。由用户通过安全环境入口提供签名口令（不要在聊天里发送），确认允许可恢复的真实自启/权限测试。
3. 在临时目录/旧安装备份保护下完成同一候选的安装与App实测。必须先满足Windows测试/真实exe门禁；没有门禁不得宣称正式Mac验收通过。
4. 完成有效更新签名、验证并新增四件套，再 annotated Tag、Push与远端核验。当前不创建假完成Tag。
5. 若封版前修复运行代码，重新构建并核对候选哈希；不可覆盖任何已封版产物。若2.8.2已被别处封版则递增版本。

最新报告：[task-1.md](task-1.md)，证据：[TEST_EVIDENCE.md](TEST_EVIDENCE.md)，744行矩阵：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)。包含29条动态菜单、7条通用编辑菜单和8条Windows2.8.0新增/变更操作；源码发现项含重复入口与条件候选，不代表744项Windows独立功能已全部核实。

矩阵当前统计：未检查713，已实现待实测22，环境阻塞9，测试失败0，原生等效已验证0，对齐已实测0。实机调试已验证设置可见、权限页可读（屏幕录制已授权，辅助功能/输入监控未授权）、关闭设置后PID78203仍在；但未完成各项完整验收用例，不提升状态。Dock AX超时；Finder列表曾追踪已移到备份的旧inode，后续必须重新导航并核对完整URL，不得误开备份。旧失败保留于证据，DIST-01等待c7e78a3的实际包体验证。
