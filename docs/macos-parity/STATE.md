# Mac 对齐任务状态

更新：2026-10-19（Asia/Shanghai）。任务1 阻塞未闭环；**任务2 已完成开发与自主测试（v2.9.0，Mac 四件套已出）**，不合回 main，待用户人工验收并在控制中心发布。任务3～5 未执行。

## 唯一接续目录

- 工作目录：`/Users/sunlei/codex/jietuba`
- 分支：`fix/macos-native-parity`。不合回 main。
- Windows 最新正式源码Tag：v2.8.0 / `7c0d289475ee630a4102f2b7e36b9aa8e49bb54c`，2026-10-19；main仍停在v2.7.0/a26380e。
- Windows 正式软件基线：已下载公开清单2.8.0的exe，SHA256/大小与清单一致，包内APP_VERSION=2.8.0；精确exe→源码SHA构建证明仍缺。旧矩阵保留a26380e行号，增量WIN280-1～8归任务3，候选Mac尚未吸收该提交。见 BASELINE.md。
- Mac 候选版本：**2.9.0（任务2已封版，Mac 四件套已入 dist/release/）**。任务2 坐标/捕获重大对齐，MINOR 2.8.2→2.9.0。版本唯一源 main/main_app.py:24。
- 任务2 前序历史候选 2.8.2（c7e78a3）保留在任务1 记录中。
- 原有 README.md / README_zh-CN.md / README_JA.md 草稿和 graphify-out-main/ 保留，未纳入本任务提交。
- 旧 worktree `/Users/sunlei/codex/jietuba-unified`、`/Users/sunlei/codex/jietuba-macos` 未改动；不可从旧分支覆盖本轮修复。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| 1 | 阻塞 | 更新签名与Windows定向构建门禁已解除；安装App实测、Mac CI和公开分发条件未闭环 |
| 2 | 已完成（待人工验收） | 捕获/画布/10标注/编辑/输出对齐，v2.9.0 四件套已出；184条=79对齐/3原生/102待实测；见 task-2.md |
| 3 | 阻塞 | 尚未执行，等待前置任务与用户调用 |
| 4 | 阻塞 | 尚未执行，等待前置任务与用户调用 |
| 5 | 阻塞 | 尚未执行，等待前置任务与用户调用 |

## 当前交付与阻塞

### 任务2（v2.9.0，最新）
- Mac 四件套 `dist/release/`：`积磊截图-v2.9.0-261019-macOS-arm64.app.tar.gz`（110,401,052 B）、`.sig`（448 B，minisign，已用固定公钥验证）、`.dmg`（119,161,253 B，hdiutil verify VALID）、`v2.9.0-261019-macOS-更新说明.txt`。`.sha256` 在 dist/。旧 v2.8.1 四件套原地保留。
- `/Applications/积磊截图.app` = 2.9.0（arm64，codesign 有效，Apple Development；spctl rejected，未公证）。
- 核心改造：macOS capture 改 CG 物理像素（7680x2160）+ 场景物理像素/窗口 point；QTest 真实鼠标事件 10/10 工具绘制、撤销重做、5 格式导出、专属设置 12/12。详见 task-2.md / TEST_EVIDENCE.md。
- 待用户：人工验收 → 把四件套拖入积磊控制中心发布中心（analyze→stage→publish）；混合 dpr 无设备记环境阻塞。

### 任务1（历史，2.8.2）
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

矩阵统计（744行）：任务2（184条）已更新为 对齐79 / 原生3 / 待实测102；全矩阵当前对齐已实测79、原生等效3、已实现待实测102、未检查483，其余约77行为任务1填入的待办/阻塞描述（其状态列含文字，非标准枚举）。任务2 真实 App 选区/工具栏实测、QTest 真实鼠标事件为新增关键证据。

（历史）任务1：本轮PID13381，系统设置显示辅助功能/输入监控均为on，但App内授权后恢复未验证；Dock AX超时；Finder列表曾追踪已移到备份的旧inode，后续必须重新导航并核对完整URL。DIST-01的c7e78a3实际包体验证已补齐，不能替代Windows交互实测。
