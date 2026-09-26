# Windows / macOS 统一代码树整合记录

本分支为整合验证分支，不是正式发布。版本保持 **2.4.0**。构建通过不等于人工功能验收通过。

## 基线与隔离

- Windows：`3e77cd2f40d6b2a940795ef2585923b512a233d5`（最新 `origin/master2`）。
- macOS：`9117929c2e8da7ae2a122cd0d7769b7846d37b1c`。
- 共同祖先：`4fc8287ec2ca0ae9c1b50083c8dc0184cd845b90`。
- 已有合并：`2c39616d19bc5fb89882963125e4574a20a0e755`；已有打包修复：`90fd6247bb75e4abab9cdc31d0217f85097810e2`。
- 本轮沿用远端 `integration/unified-platform`，独立 worktree：`/Users/sunlei/codex/jietuba-unified`。
- 不切换、不改写 `master2` 或 `cross-platform-macos`，不覆盖 Tag，不执行正式发布。
- 实际远端还有 `gitea`；本次按用户指定只推送 `origin` 整合分支。

用户参考的 Windows 2.2.0 之后还有 2.3.0 的数字快捷键与工具栏自定义、2.4.0 的工具栏排序、备注间距和剪贴板列表显示方案；整合以 2.4.0 为回归基准。

## 重叠文件与冲突

共同祖先之后双方均修改的文件共 10 个：`.gitignore`、`AGENTS.md`、三语 README、`main/main_app.py`、`main/settings/tool_settings.py`、`main/tests/test_text_effects.py`、`main/ui/settings_ui/dialog.py`、`main/ui/settings_ui/page_hotkey.py`。

使用 `git show --remerge-diff 2c39616` 核实历史文本冲突，而不是重新合并或选择整文件 ours/theirs：

- `.gitignore`：add/add；合并 Windows 构建/测试临时文件与 macOS、venv、Rust 产物规则。
- `AGENTS.md`：add/add；统一双平台边界、分支模型、唯一应用版本、双端构建与发布要求。本轮再消除默认直接改 master2 与短期分支规则的矛盾，统一 SemVer Tag，保留历史 Tag。
- 其他重叠文件不产生文本冲突，但逐项检查业务语义：main_app 保留 2.4.0 并增加权限引导；设置保留 Note/Text/快捷键迁移并增加 Mac 日志目录；设置页保留新快捷键与 Mac 权限页；README 保留最新功能并说明验收状态。

## 保留与边界

| 区域 | 内容 |
| --- | --- |
| 共享业务 | Canvas、Note AUTO/FREE、独立拖动、箭头重连、文字双模式、宽度/字号、撤销重做、克隆、钉图画布、工具栏、设置、多语言、OCR/翻译工作流、剪贴板数据模型 |
| `platforms/base` | capture、window、hotkey、clipboard、accessibility、coordinates、permissions 契约 |
| `platforms/windows` | mss、Win32 快捷键/剪贴板/窗口能力、UIA 适配、Windows 坐标及权限实现 |
| `platforms/macos` | mss/屏幕权限、CGWindowList、AX、Carbon、Command 粘贴、坐标、TCC |
| Rust/打包 | Windows capture 与 macOS ScreenCaptureKit 两套底层；共享编码/拼接/OCR/存储；Windows onefile 与 macOS app/DMG/签名脚本 |

Canvas、tools、Note 面板、截图工具栏、钉图画布/工具栏和翻译资源保持与 Windows 2.4.0 基线相同。没有复制第二套 Mac 业务源码。

## 本轮发现和修复

- CI 没有对整合分支触发；现加入整合分支 push，Windows x64/ARM64 先运行、macOS 依赖 Windows 完成。
- Windows CI 增加当前提交真实 onefile 构建、OCR 模型、版本/SHA/文件大小/SHA-256 清单与产物上传。
- 整合树原有 37 条 lint 问题，包括欢迎页缺失导入；修复缺陷与未使用导入，补全必须实现的平台抽象方法，不放宽 lint 规则。
- Windows Accessibility 适配器调用不存在的函数；改接现有 UIA provider，保持同线程创建/扫描/释放，失败可见；不改现有异步 UIA finder。
- Windows window backend 的缩减版枚举与错误 MONITORINFO 路径；改复用成熟 WindowFinder，保留过滤、DWM、UWP 与副屏句柄修复。
- macOS 剪贴板适配器缺少控制器调用入口、复制误发 V；补入口并区分 C/V，设置 Command flag，异常仍抬起按键，移除 PyObjC 对象的手动释放。
- macOS 智能翻译的原生按键代码移入现有剪贴板 backend，去掉该处静默吞错；快捷键显示与实际 Command 注册一致。
- Mac Rust capture 清空队列时丢弃新帧；保留最新帧并加 Rust 回归用例，Windows capture 不变。
- Mac 环境脚本改用本轮独立 wheel 临时目录，避免混装别的任务旧 wheel；构建不再默认清空 PyInstaller 缓存。

## 尚保留的平台泄漏及风险

为避免整合时重写成熟 Windows 行为，以下保留兼容边界，不能宣称平台代码已经完全收口：

- `capture/window_finder.py`、`capture/uia_element_finder.py`：成熟 Win32/UIA 主体仍在旧路径，Windows backend 适配它们，macOS finder 单独实现；迁移应另做兼容导出与调用链验收。
- `clipboard/controllers/foreground_tracker.py`、`paste_keystroke.py`：Windows 句柄/焦点恢复原实现与平台分派仍在控制器；本轮不调整其时序。
- `core/shortcut_manager.py`：原生 WM_HOTKEY 过滤和鼠标侧键监听仍在共享管理器；迁移涉及全局快捷键去重与生命周期，不做大规模改写。
- `core/platform_utils.py`：DPI、工作集、进程身份与窗口捕获排除兼容函数仍有 Win32 实现。
- `gif/*`、`stitch/scroll_window.py`：鼠标/穿透/滚动调用仍有平台分支；不能只凭 Qt 导入成功认为穿透、录屏、多屏完全可用。
- `main_app.py`、设置页、欢迎页、数据目录：存在权限入口、路径、自启动与桌面快捷方式分派。
- SCK 现有实现只选择单个显示器，跨显示器区域会裁切；Retina/多屏/GIF 必须人工验收。原有异步启动/停止与回调上下文生命周期仍需真机专项验证，未在此重写。
- 已有 Mac 字形轮廓测试有 darwin skip。本轮没有新增该 skip；它不能算 Mac 字形验收证据。

## 验证记录

以 GitHub Actions 实际运行和当前提交产物清单为准。历史提交声称的 Windows 2355 passed / 7 failed / 13 skipped 与旧 exe 不作为本轮通过证据。

本轮 Windows / macOS 测试与构建仍在执行；以下人工项均未自动判定通过。

首轮 Windows ARM64（`9a490b9`）实际结果：2377 passed / 7 failed / 13 skipped，覆盖率 61.57%。
七项失败为：快捷键表默认值三项、OCR 工具栏升级顺序一项、工具栏排序/拖动两项、工具栏会话替身缺失刷新方法一项。
修复方式：截图快捷键表从唯一配置默认源取值；允许合法的未绑定空字符串；按 2.4.0 数字顺序检查升级与拖动；补齐替身并断言刷新调用。未删除或 skip 失败测试。

## Windows 人工回归清单

- [ ] 启动、托盘、退出/重启。
- [ ] 主截图快捷键、备用截图快捷键、数字快捷键、自定义键与文字输入不抢键。
- [ ] 多显示器、副屏、不同 DPI、区域截图。
- [ ] 智能窗口框选、元素级智能选区、滚轮切粒度。
- [ ] 复制、保存、OCR、翻译。
- [ ] 长截图、横/纵滚动、GIF 与鼠标/标注覆盖层。
- [ ] 钉图、克隆、导出、置顶恢复。
- [ ] 剪贴板历史、快速粘贴、前台目标恢复、三种列表显示方式。
- [ ] Note AUTO/FREE、目标框与文字独立移动、目标框缩放、箭头连接、文字宽度/字号。
- [ ] 文字双模式、所有主要标注、撤销/重做。
- [ ] 工具栏排序/显示设置、设置保存与重启恢复。
- [ ] 对比原 Windows 2.4.0：既有能力不减少。

## Mac 人工回归清单

- [ ] 源码启动、托盘、打包 app 启动。
- [ ] 屏幕录制、Accessibility 权限、拒绝/恢复授权、TCC 跨重启/升级持久性。
- [ ] Retina、多显示器、负坐标、副屏截图、智能窗口与元素选区。
- [ ] 全局快捷键、Command/Ctrl 映射、显示/录入/实际注册一致。
- [ ] 剪贴板、Command+C/V、目标应用恢复、不粘贴到自身。
- [ ] 钉图、OCR、Note、文字、主要标注、撤销重做。
- [ ] 长截图横/纵滚动、鼠标穿透、GIF 画面更新与录制停止。
- [ ] Apple Development 签名、app 与 DMG、唯一版本号与 OCR 资源。
- [ ] 正式分发另验 Developer ID + 公证；本任务不是正式发布。
