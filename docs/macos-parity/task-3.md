# 任务3：日常系统功能对齐

状态：开发与本机原生验证完成，收尾实测已补齐；遗留项已逐条列明，仍未整体“通过”。候选 2.10.0（源码 `c2fec4e`）。2026-10-19（Asia/Shanghai）。

工作目录 `/Users/sunlei/codex/jietuba`；分支 `fix/macos-native-parity`，不合并 main。
本轮起点 c6b070ed98b27f788230347e6644be34c0173d92。
Windows 稳定基线 v2.8.0 / 7c0d289475ee630a4102f2b7e36b9aa8e49bb54c；fetch 后无新增远端变化。

## 已开发

- 统一平台快捷键约定，Mac 录入/加载/菜单显示 Command，Windows 保持 Ctrl；Mac 物理 Control 单独保存 lctrl，Option 保持 alt。配置按可移植 token 保存。
- 修复应用内 Meta/Control 丢失、半截组合键释放、已注册全局键在录入时按 Win32 位误解码；Carbon 临时注册探测占用后释放。
- 安全吸收 Windows 2.8.0 共享剪贴板顶部搜索、图片 OCR 索引/历史补录、四档预览及 Rust 数据库迁移。不覆盖版本和启动修复。
- OCR 失败不写成已完成空结果；队列加锁；移除识别文字日志，避免记录个人剪贴板内容。
- 自动粘贴目标不存在/本应用/焦点超时，停止且提示；不再向未知前台盲发。
- 修复任务2物理像素画布与 CG/AX 逻辑点智能选区错位；排除自身窗口；AX 仅扫描匹配目标窗口。

## 测试与候选构建

项目 Python3.11.16、Qt6.8.3、macOS arm64，QT_QPA_PLATFORM=cocoa。
本轮测试分批运行于 build/task3-*.log，各失败及修复保留，不删除旧结果。
19模块定向门禁已通过（build/task3-gate.log），另行回归显示/智能选区修改。
Rust pyclipboard 6项通过；maturin 原生 wheel 已重新构建安装到项目 venv。
真实候选 App 已由 build_macos.py 构建成功，资源/架构/模型/四原生库和 codesign 校验通过。
此处尚不代表真实 App、Windows 原生门禁或公开分发通过；四件套和最终证据待追加。

## 待完成/外部限制

本轮 Windows 精确 SHA 测试和真实 exe 构建、最新 App 安装及真实操作证据待执行。
Developer ID、公证、Windows 交互环境、鼠标侧键实体设备、混合DPR和最低系统环境不足，分别记录，不冒充通过。
翻译仅做离线契约，不使用真实用户密钥或计费服务。任务4/5不在本轮执行。

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

## T3-20261019-R：收尾实测（真实 App 跨应用往返与残留问题）

- 真实 App 跨应用往返 10 轮（TextEdit 5 轮 + Chrome 5 轮）：复制 → 剪贴板历史最新条目 → 粘贴回原目标，接收内容与期望逐字一致，粘贴后前台回到原目标应用；全局热键 ⌘⇧V 由真实系统事件触发，共 22 次打开剪贴板窗口 0 崩溃。脚本 `build/task3-resume-clipboard-loop.py`，原始输出 `build/task3-resume-clipboard-10rounds.log`。
- 重复内容 3 轮通过；复制后切换目标（TextEdit→Chrome）粘贴精确落到唤起时前台目标；目标失效保护在 22:05:45 真实触发一次（`已停止自动粘贴`），本轮两种构造未再触发，原因是 macOS 粘贴目标按 PID 粒度跟踪（见 `main/clipboard/controllers/foreground_tracker.py` 注释），与 Windows 的 HWND 粒度存在已记录差异，不冒称完全一致。
- 定向本机门禁 20 模块退出 0（`build/task3-resume-gate.log`）：Windows 专属 clipboard_paste_target(7)/mouse_hotkey(28) 在本机 skip，其余全部通过；Rust pyclipboard 与原生 wheel 沿用同批已安装结果。
- 四件套复核：`.sig` 以客户端固定公钥独立验证通过（`sunget-tauri/src-tauri/tools/verify-updater-signature.mjs` 退出 0）；四文件 SHA256 与 `dist/积磊截图-v2.10.0-261019-macOS-arm64.sha256` 一致；归档内 App 主程序二进制与已安装 App 相同（`688871e2…e49299`）。此前记录中的 `ceab8d9c…` 是更早一次中间构建的哈希，已按最终产物更正。
- 顺带修复仓库自身的 README 目录树一致性问题（纯文档）：删除不存在的 `page_about.py` 行、补上 `clipboard/services/ocr_index_service.py` 与 `core/instance_broker.py`，`main/tests/test_readme_tree.py` 由 3 failed 变为 3 passed。
- 发现未在应用层修复的残留（转任务5）：
  1) AX 客户端（Computer Use / VoiceOver 一类）在剪贴板窗口重建列表期间触发 Qt 段错误，22:09–22:52 共 6 份崩溃报告（`QAccessibleCache::deleteInterface`、libqcocoa `__RELEASE_OBJECTS_IN_THE_ARRAY__`）；无 AX 客户端时 22 次打开 0 崩溃，根因在 Qt 6.8.3/PySide 无障碍服务代码，应用层无安全修复手段，建议在 PySide6 补丁版本复测。
  2) `capture/window_finder.py` 在 macOS 导入时打印 `win32gui 未安装，智能选区功能不可用` —— 可用性实际由 `platforms/macos/window_finder.py` 提供（模块底部已分派），此行是 Win32 分支的日志噪声，易被误读为功能被关闭。
- 环境阻塞/未实测（不计通过）：钉图 5 轮（创建/编辑/复制/关闭/多钉图/穿透）需真实鼠标或 AX 交互，而 AX 交互会触发上述 Qt 崩溃；29 条动态剪贴板右键菜单、7 条通用编辑菜单、智能选区滚轮粒度同样未逐条实测，转任务5 与用户人工验收。
- 本次收尾未修改任何运行代码，因此沿用 v2.10.0 已构建的四件套，不重新出包、不覆盖历史产物；测试用合成内容，用户原剪贴板在测试前本地备份、结束后恢复，未打印或入库任何真实剪贴板内容。
