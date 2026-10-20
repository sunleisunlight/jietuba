# Mac 对齐任务状态

更新：2026-10-20（Asia/Shanghai）。任务1-4 已完成；**任务5 已完成全量测试修复与 Mac 四件套交付（v2.11.2）**。均不合回 main。

## 唯一接续目录

- 工作目录：`/Users/sunlei/codex/jietuba`
- 分支：`fix/macos-native-parity`。不合回 main。
- Windows 最新正式源码Tag：v2.8.0 / `7c0d289475ee630a4102f2b7e36b9aa8e49bb54c`，2026-10-19；main仍停在v2.7.0/a26380e。
- Windows 正式软件基线：已下载公开清单2.8.0的exe，SHA256/大小与清单一致，包内APP_VERSION=2.8.0；精确exe→源码SHA构建证明仍缺。旧矩阵保留a26380e行号，增量WIN280-1～8归任务3，候选Mac尚未吸收该提交。见 BASELINE.md。
- Mac 候选版本：**2.11.2（任务5最终封版，Mac 四件套已入 dist/release/）**。任务5 全量测试套件修复与 ruff lint 修复，PATCH 2.11.0→2.11.1→2.11.2。版本唯一源 main/main_app.py:24。
- 任务2 前序历史候选 2.8.2（c7e78a3）保留在任务1 记录中。
- 原有 README.md / README_zh-CN.md / README_JA.md 草稿和 graphify-out-main/ 保留，未纳入本任务提交。
- 旧 worktree `/Users/sunlei/codex/jietuba-unified`、`/Users/sunlei/codex/jietuba-macos` 未改动；不可从旧分支覆盖本轮修复。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| 1 | 已完成（待人工验收） | 捕获/画布/标注/编辑/输出对齐，Apple Development 签名；公开分发因缺 Developer ID 公证阻塞 |
| 2 | 已完成（待人工验收） | 画布/标注/编辑/输出对齐，v2.9.0 四件套已出；见 task-2.md |
| 3 | 已完成（待人工验收） | 快捷键/剪贴板/OCR/翻译对齐，v2.10.0 四件套已出；AX 客户端下剪贴板窗口 Qt 段错误记残留；见 task-3.md |
| 4 | 已完成（待人工验收） | 长截图/GIF录制坐标单位对齐，v2.11.0 四件套已出；见 task-4.md |
| 5 | 已完成（待人工验收） | 全量测试修复（2529 passed / 138 skipped）+ ruff 通过 + Windows CI 通过，v2.11.2 四件套已出；见 task-5.md |

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

## 2026-10-19 18:55：任务3最终候选复测与修复

- 最终候选源码提交 `c2fec4e`，版本 `2.10.0`，分支 `fix/macos-native-parity`；未合并 main。
- 快捷键：Mac 持久化继续使用跨平台 `ctrl`，界面显示 Command；物理 Control 显示 Control，Option 显示 Option；Windows 仍显示 Ctrl。Finder 双击 `/Applications/积磊截图.app` 后真实设置页显示 `Command+Shift+a` 及 `例如: Command+Shift+a`；实按 Command+Shift+k 显示 `Command+Shift+k`，实按 Control+Option+k 显示 `Option+Control+k`。证据截图 `build/task3-command-final.png`。
- 真实候选 App 主程序 SHA256 `ceab8d9c0c64eba291fd41f5109bb3f345be7286d06ebf041c8776c79f0ea794`；`build_macos.py` 退出0，Apple Development 深度签名校验通过，spctl 因缺 Developer ID/公证拒绝，不能作为公开分发结论。
- 真实原生 OCR：`build/task3-native-content.log`，PP-OCRv6 对合成中英混排/数字/多行样本逐行返回预期文本；zxing-cpp 对合成 QR 与 Code128 返回预期内容。
- 新增 Azure provider 离线 HTTP/错误契约测试；快捷键提示改为只转换文本中的快捷键示例，不改变翻译文案。
- 修复 Mac Carbon 全局热键事件常量：HIToolbox `kEventHotKeyPressed/Released` 为 5/6（此前误用1/2导致注册成功但收不到事件）。Apple SDK 头文件核对，新增回归测试；此前真实剪贴板热键未唤起窗口的现象由此解释。
- 修复 Mac 粘贴目标追踪：通过 AX focused window 记录 PID兼容 token，发送前再次核对窗口身份；无法核对则停止并提示，不向当前错误窗口盲粘。用户原剪贴板仅在本地安全文件临时保存后恢复，未输出内容。
- 任务3定向本机测试最终批次：`build/task3-final-tests.log`，退出0；OCR/扫码/翻译/剪贴板/快捷键模块通过。Rust pyclipboard 6项通过，maturin wheel 已安装。
- Windows CI 定向任务3运行 `39235405307`（提交 `3f679dd`）x64/ARM64测试与真实exe构建通过；最新含 Carbon 修复的运行 `39240802180` 待完成。Mac CI同批受 ScreenCaptureKit runner 无屏幕录制环境影响，`record_session_basic` 0帧失败，不是快捷键/剪贴板回归。
- Mac四件套已生成且 `.sig` 使用密钥验证脚本核验通过；产物路径与SHA见 `build/task3-release.log` 及 `dist/积磊截图-v2.10.0-261019-macOS-arm64.sha256`。旧 release 未删除。

结论：任务3代码与本机原生验证完成；跨 Windows 的 CI 任务3主线在最新提交待完成，公开分发与真实多轮跨应用粘贴/钉图循环仍需最终人工验收，任务状态保持“进行中”。

## 2026-10-19 23:20：任务3 收尾（真实 App 往返实测 + 残留登记）

- 候选 `2.10.0`，源码 `c2fec4e`，分支 `fix/macos-native-parity`，未合并 main；本轮只补文档与测试记录，未改运行代码，因此沿用同一份已构建四件套，不重新出包。
- 真实 App 跨应用往返 10 轮（TextEdit 5 + Chrome 5）全部通过：接收内容逐字一致、焦点归还原目标；⌘⇧V 全局热键 22 次打开剪贴板窗口 0 崩溃；重复内容 3 轮、目标切换用例通过。证据 `TEST_EVIDENCE.md` 批次 T3-20261019-R、`build/task3-resume-clipboard-10rounds.log`。
- 四件套完整性复核：`.sig` 用客户端固定公钥独立验证通过；四文件 SHA256 与 `dist/积磊截图-v2.10.0-261019-macOS-arm64.sha256` 一致；归档内 App 主程序与 `/Applications/积磊截图.app` 同一二进制（`688871e2…e49299`）。task-3.md 中旧的 `ceab8d9c…` 中间构建哈希已更正。
- 顺带修复 README 目录树一致性（纯文档），`test_readme_tree.py` 3 failed → 3 passed。
- 转任务5 的残留：① AX 客户端（Computer Use/VoiceOver）下剪贴板窗口重建列表会触发 Qt 段错误（6 份崩溃报告；无 AX 客户端 22 次打开 0 崩溃，根因在 Qt 6.8.3/PySide 无障碍代码）；② macOS 导入时 `win32gui 未安装，智能选区功能不可用` 只是日志噪声（可用性由 `platforms/macos/window_finder.py` 提供）。
- 环境阻塞未通过项：钉图 5 轮、动态剪贴板右键菜单 29 条、通用编辑菜单 7 条、智能选区滚轮粒度 —— 均需真实鼠标或 AX 交互，AX 交互会触发上述崩溃，转任务5 与用户人工验收。
- 用户原剪贴板在测试前本地备份（`build/task3-resume-pasteboard.plist`，未入库、未打印内容），结束后已恢复；剪贴板历史中会留有本轮合成测试条目。
- 下一步：由用户人工验收 → 把 `dist/release/` 的 v2.10.0 四件套拖入积磊控制中心发布中心（analyze→stage→publish）；任务4（长截图/录制）为下一任务入口。

## 2026-10-20 01:10：任务4 完成（长截图/GIF录制坐标单位对齐）

- 候选 `2.11.0`，源码见本轮 Commit，分支 `fix/macos-native-parity`，未合并 main。
- 核心修复：Retina 下录制/长截图坐标系单位错乱（窗口尺寸翻倍、画面重复、分辨率减半）。统一"场景=物理像素、屏幕=Qt 逻辑点"；GIF 录制以点定区域、像素定输出；长截图改用物理像素全桌面捕获+按像素裁剪。
- 新增平台 input backend（`pointer_buttons`/`send_scroll`），Windows/macOS 共享业务逻辑；`base/coordinates` 新增 `reference_factor()`。
- Rust `gifrecorder`：`RecordSession`/`ScreenCapture` 新增 `out_width/out_height` 参数；ObjC `JTKStartCapture` 新增 outW/outH 且不再排除自身窗口（标注入帧）。20 项 Rust 测试通过。
- 本机管线验证（非 mock）：GIF 录制 Retina dpr=2，400x300 点 → 800x600 像素输出，14 帧非黑屏；长截图 7680x2160 物理像素全桌面，裁剪正确非黑屏。
- Python 回归：`test_frame_recorder` 28 passed（新增点→像素换算测试）、`test_macos_coordinates` 7 passed、gif/stitch/platform 套件 185 passed / 6 skipped。
- Mac 四件套已生成：`dist/release/积磊截图-v2.11.0-261020-macOS-arm64.{app.tar.gz,app.tar.gz.sig,dmg}` + 更新说明；DMG hdiutil verify VALID；`.sig` 448 B。旧 release 未删除。
- 公开分发阻塞：仅有 Apple Development 签名，无 Developer ID + 公证凭据。
- 待人工验收：长截图真实滚动拼接（浏览器+文本编辑器纵/横向）、GIF GUI 选区/标注入帧/导出、录制停止后焦点与鼠标穿透恢复。

## 2026-10-20 02:10：任务5 完成（全功能复核 + 测试修复 + v2.11.2 四件套）

- 最终候选 `2.11.2`，源码 `c006b3d`，分支 `fix/macos-native-parity`，未合并 main。
- Windows 基线重新核实：最新正式 v2.8.0 / `7c0d289`，无新增变更。
- Python/Qt 全量测试：首跑 7 项失败全部定位修复（Retina dpr 假设、缺失字体、边缘热区、模态窗口污染、缺失导入、快捷键显示大小写、坐标恒等断言）。修复后 **2529 passed / 138 skipped**（1 项全量套件偶发 flaky，隔离与模块级均通过）。
- Rust workspace：gifrecorder 20 / longstitch 2 / pyclipboard 6 全部通过。
- ruff lint：All checks passed（移除未用 QCursor；text_settings_panel 加入 F401 白名单，BACKGROUND_PRESET_STYLES 为有意重导出）。
- Windows CI（run 39299437695）：x64 success + arm64 success。macOS job 仅 `record_session_basic` 失败（CI runner 无屏幕录制权限，19/20 通过）。
- DMG 安装到 /Applications 验证通过：v2.11.2 arm64，双击启动成功，OCR/剪贴板/热键/钉图全部初始化，设置与历史数据跨版本保留。
- 更新链路代码审计通过：factory 返回 macOS updater，download/extract/verify/install 全链路有校验与原子替换。
- Mac 四件套 v2.11.2 已生成：app.tar.gz(110MB) + .sig(448B) + .dmg(119MB) + 更新说明；SHA256 记录在 dist/；旧产物原地保留。
- Commit `c006b3d` + annotated Tag `v2.11.2` 已推送 origin。
- 残留：① AX 客户端下剪贴板窗口 Qt 段错误（Qt 6.8.3 无障碍代码，非业务代码）；② macOS CI 无屏幕录制权限；③ 公开分发缺 Developer ID + 公证。
- 待人工验收：30 轮截图、10 轮剪贴板粘贴、5 轮录制、全部编辑工具、长截图拼接、钉图与右键菜单、设置持久化。
