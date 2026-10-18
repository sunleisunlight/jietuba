# Mac 对齐任务状态

更新：2026-10-19（Asia/Shanghai）。任务1 **阻塞，未通过**。不要自动执行任务2～5。

## 唯一接续目录

- 工作目录：`/Users/sunlei/codex/jietuba`
- 分支：`fix/macos-native-parity`。不合回 main。
- Windows 源码基线：v2.7.0 / `a26380ea80f73af029e7fc5f0ada65584fa1ef92`，2026-10-17。
- Windows 正式软件基线：**待核验**，未取得可追溯的正式 exe。见 BASELINE.md。
- Mac 候选版本：2.8.2；源码提交 `c5ac3985a90a75d89a8faa2aabcebf6d4fe34372`，已推送origin并用ls-remote核验。本记录后续纯文档提交不改变候选App代码。
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

- `.app`：`/Users/sunlei/codex/jietuba/dist/积磊截图.app`（2.8.2，arm64，Apple Development）。资源、原生依赖、签名校验通过；Gatekeeper 拒绝，未公证。
- 最新暂存目录：`/Users/sunlei/codex/jietuba/dist/macos-release-i22urk_u/`，有 app.tar.gz、DMG、更新说明；**缺少有效 .sig，未形成四件套**。此前ujgi7u90为调试迭代，保留但不是最新候选，勿交付。
- `dist/release/` 的 v2.8.1 四文件未删除/覆盖/移动；没有把半套2.8.2放入 release。
- 签名使用已有私钥路径；当前会话未注入口令，单次空口令尝试返回 Wrong password。停止尝试，不读取密码/私钥、不猜测凭据。
- 旧安装 `/Applications/积磊截图.app` 为2.8.1，PID59837。两次 Computer Use 获取该App超时，Dock获取也超时，Finder可用。`sample`显示主线程在正常事件循环等待，**不能据此断言进程挂死**。未终止、未替换旧App。
- 自启开关、权限撤销/授权、真实首次配置和实际重新登录尚未测试；未改变用户真实TCC或LaunchAgent。
- Windows候选CI：[39166063824](https://github.com/sunleisunlight/jietuba/actions/runs/39166063824)，精确SHA=c5ac3985a90a75d89a8faa2aabcebf6d4fe34372；已显式dispatch任务1定向门禁，当前运行中，不能算通过。完整套件默认流程未关闭。
- 正式Tag `v2.8.2` 未创建，四件套/真实App验收未闭环，不冒称正式发布完成。没有生产发布、没有合回main。

## 接续顺序

1. 核验本文件记录与当前Git状态；查看候选CI的确切SHA结果。
2. 由用户通过安全环境入口提供签名口令（不要在聊天里发送），安全退出旧版，确认允许可恢复的真实自启/权限测试。
3. 在临时目录/旧安装备份保护下完成同一候选的安装与App实测。必须先满足Windows测试/真实exe门禁；没有门禁不得宣称正式Mac验收通过。
4. 完成有效更新签名、验证并新增四件套，再 annotated Tag、Push与远端核验。当前不创建假完成Tag。
5. 若封版前修复运行代码，重新构建并核对候选哈希；不可覆盖任何已封版产物。若2.8.2已被别处封版则递增版本。

最新报告：[task-1.md](task-1.md)，证据：[TEST_EVIDENCE.md](TEST_EVIDENCE.md)，700行矩阵：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)。源码发现项含重复入口与条件候选，不代表700项Windows独立功能已全部核实。

矩阵当前统计：未检查669，已实现待实测21，环境阻塞10，测试失败0，原生等效已验证0，对齐已实测0。无已验证状态不等于代码完全不可用；只表示本轮打包App证据尚未取得。
