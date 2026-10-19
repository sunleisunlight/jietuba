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
| 1 | 阻塞 | 更新签名与Windows定向构建门禁已解除；安装App实测、Mac CI和公开分发条件未闭环 |
| 2 | 阻塞 | 尚未执行，等待任务1与用户调用 |
| 3 | 阻塞 | 尚未执行，等待前置任务与用户调用 |
| 4 | 阻塞 | 尚未执行，等待前置任务与用户调用 |
| 5 | 阻塞 | 尚未执行，等待前置任务与用户调用 |

## 当前交付与阻塞

- `.app`：`/Applications/积磊截图.app`（2.8.2，arm64，Apple Development；构建源 `c7e78a3`）。资源、原生依赖、签名校验通过；Gatekeeper 拒绝，未公证。修复后终端启动进程持续运行并可读设置 AX 树；Finder/Dock真实循环尚未完成。
- 最新暂存目录：`/Users/sunlei/codex/jietuba/dist/macos-release-sz88t8x3/`，app.tar.gz、有效.sig、DMG、更新说明四文件已齐；更新签名已用固定公钥验证。尚未封版或新增到release。此前u4oz6qdm/i22urk_u/ujgi7u90均为旧调试迭代，保留但不是最新候选，勿交付。dist/积磊截图.app 已恢复为与安装包相同的副本。
- `dist/release/` 的 v2.8.1 四文件未删除/覆盖/移动；没有把半套2.8.2放入 release。
- 用户明确提供的更新签名凭据路径已写入AGENTS.md；口令静默读取到签名子进程，未输出、入库或写入命令行参数。此目录不含Apple Developer ID证书或公证凭据；历史Wrong password记录不代表当前阻塞。
- 旧安装原PID59837已退出并由 `dist/task1-install-backup-4BgqPj/积磊截图-v2.8.1-installed.zip` 保留；上一轮候选也在同目录。替换未清理用户数据。修复后 Finder 定位可见2.8.2，但实际三轮双击/重复打开/退出重开仍待确认；此前AX超时不能作为新候选运行证据。
- 自启开关、权限撤销/授权、真实首次配置和实际重新登录尚未测试；未改变用户真实TCC或LaunchAgent。
- Windows定向CI：[39170509042](https://github.com/sunleisunlight/jietuba/actions/runs/39170509042)，精确源码c7e78a3，x64/ARM64测试及真实exe构建成功；本机已下载x64产物并验证manifest哈希、QtNetwork DLL/pyd及PYZ内comtypes.shelllink/persist。Mac job失败于ppocr_rust/onnxruntime链接。完整流程39169825988的Windows测试另有6项失败，不能称全量CI通过，详见证据J。
- 正式Tag `v2.8.2` 未创建，四件套/真实App验收未闭环，不冒称正式发布完成。没有生产发布、没有合回main。

## 接续顺序

1. 核验本文件记录与当前Git状态；查看候选CI的确切SHA结果。
2. Windows x64实际exe核对和有效更新签名已完成，不再要求用户重复提供口令。系统设置已只读确认积磊截图的辅助功能、输入监控均为on；未撤销权限。用户已允许可恢复自启测试，但尚未执行。
3. 在临时目录/旧安装备份保护下完成同一候选的安装与App实测。必须先满足Windows测试/真实exe门禁；没有门禁不得宣称正式Mac验收通过。
4. 当前App导航自动化仅改变选中态、内容仍停留快捷键页；需区分Qt AX操作限制与真实鼠标导航故障，再继续App内权限刷新、自启和生命周期实测。完成后校验暂存四文件、只增新增release，再annotated Tag、Push与远端核验。
5. 若封版前修复运行代码，重新构建并核对候选哈希；不可覆盖任何已封版产物。若2.8.2已被别处封版则递增版本。

最新报告：[task-1.md](task-1.md)，证据：[TEST_EVIDENCE.md](TEST_EVIDENCE.md)，744行矩阵：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)。包含29条动态菜单、7条通用编辑菜单和8条Windows2.8.0新增/变更操作；源码发现项含重复入口与条件候选，不代表744项Windows独立功能已全部核实。

矩阵当前统计：未检查713，已实现待实测22，环境阻塞9，测试失败0，原生等效已验证0，对齐已实测0。历史PID78203权限读数已过时：本轮PID13381，系统设置显示辅助功能/输入监控均为on，但App内授权后恢复未验证，不提升完整用例状态。Dock AX超时；Finder列表曾追踪已移到备份的旧inode，后续必须重新导航并核对完整URL，不得误开备份。DIST-01的c7e78a3实际包体验证已补齐，不能替代Windows交互实测。
