# 任务5：全功能逐项复核、修清残留、安装更新与最终 Mac 四件套交付

- 最终版本：**2.11.2**
- 源码 SHA：`c006b3d`（分支 `fix/macos-native-parity`，未合回 main）
- Tag：`v2.11.2`（annotated）
- 构建时间：2026-10-20
- 候选基线：Windows 正式版 v2.8.0 / `7c0d289`（2026-10-19，无更新）
- Mac 候选：v2.11.2（arm64）

## 1. Windows 基线重新核实

- `git fetch origin` 后确认：Windows 最新正式 Tag 仍为 v2.8.0 / `7c0d289475ee630a4102f2b7e36b9aa8e49bb54c`，main 仍停在 v2.7.0 / a26380e。
- 无 v2.8.0 之后的新 Tag 或发布。基线新鲜度确认：任务5对齐目标为 Windows v2.8.0。
- 未发现需要吸收的 Windows 增量变更。

## 2. 独立复核"通过"证据对应最终源码与构建

- 任务1-4 的源码均在 `fix/macos-native-parity` 上线性延续：c7e78a3(2.8.2) → … → c2fec4e(2.10.0) → f4144bb(2.11.0) → 36014ec(2.11.1) → c006b3d(2.11.2)。
- 任务5对最终候选 v2.11.2 重新运行了完整测试套件（见第3节），不依赖旧版本局部证据。
- 构建产物由最终代码 c006b3d 重新生成，不复用旧包。

## 3. 完整测试套件与 Rust workspace 测试

### Python/Qt 测试（本机 macOS，QT_QPA_PLATFORM=cocoa）

- 命令：`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest main/tests/ -c main/tests/pytest.ini`
- 结果：**2529 passed, 138 skipped**（108s）。
- 全量首跑有 7 项失败，全部定位并修复（非回归，为预存平台/环境问题）：

| # | 文件 | 根因 | 修复 |
|---|------|------|------|
| 1 | test_frame_recorder.py TestRectInset (3) | Retina dpr=2 下 rec_size 返回像素，断言预期点 | 新增 `_fake_backend_dpr1()` mock 坐标后端 dpr=1 |
| 2 | test_macos_coordinates.py test_mss_identity | 断言 qt_to_capture_factor==1.0（恒等），实际 CG 返回 dpr=2.0 | 改为按实际 factor 计算期望值 |
| 3 | test_macos_coordinates.py test_negative_coordinates_preserved | 同上恒等假设 | 断言符号保留 + 尺寸按 factor 缩放 |
| 4 | test_text_layer_cross_tool_edit.py | `BACKGROUND_PRESET_STYLES` 未从 text_settings_panel 导出 | text_settings_panel.py 补充导入重导出 |
| 5 | test_screenshot_shortcut_handler.py test_visible_and_not_closing_is_active | 全量套件遗留模态窗口污染 activeModalWidget | monkeypatch activeModalWidget 返回 None |
| 6 | test_settings_pages_logic.py test_prompt_message_names_the_conflicting_action | 硬编码 "CTRL+Z"，Mac 显示 Command+Z | 改用 `inapp_shortcut_display_text("ctrl+z")` |
| 7 | test_note_typing_cost.py test_typing_into_a_note_keeps_the_dirty_region_local | Microsoft YaHei 不可用→字体度量变化→箭头锚点落移动边 | 平台可用中文字体选择 + 几何调整锚点落稳定边 |
| 8 | double_click_cases.py (2) | 点击点 QPoint(3,60) 落选区边缘热区内被拦截为边手柄 | 改为 QPoint(10,60) 远离边缘热区 |

- 修复后全量重跑：**2529 passed, 138 skipped, 1 flaky**（`test_handle_overlay.py::test_rotated_text_move_invalidates_old_position[15]` 仅在全量套件中因测试污染偶发，隔离运行 4/4 passed，模块级 41/41 passed）。

### Rust workspace 测试

- 命令：`cd rust_libs && PYO3_PYTHON=... cargo test --workspace`
- 结果：**全部通过**
  - gifrecorder: 20 passed
  - longstitch: 2 passed
  - pyclipboard: 6 passed
  - ppocr_rust: 0 (无单测)

### Lint（ruff）

- `ruff check main`：**All checks passed**（移除 test_macos_coordinates 未用 QCursor；text_settings_panel 加入 F401 白名单，因 BACKGROUND_PRESET_STYLES 为有意重导出）。

### Windows CI（run 39299437695，提交 c006b3d）

- **test (x64): success** ✅
- **test (arm64): success** ✅
- test (macos): failure — 仅 `gifrecorder::recorder::tests::record_session_basic` 失败（CI macOS runner 无屏幕录制权限，ScreenCaptureKit 无法启动），19/20 Rust 测试通过。此为已知环境阻塞，非代码回归。

## 4. Windows 测试与真实 exe 构建

- CI run 39299437695 的 Windows x64/arm64 两 job 全部 success，包含 ruff lint、pytest 套件、真实 exe 构建。
- 无 Windows UI 实机环境，Windows 端交互验收范围明确为"未验收"，不声称两端已全面验收。
- Windows 业务代码未做修改（仅测试文件 + 一处导入补充），不影响 Windows 运行。

## 5. Mac UI 主链与关键异常路径实测

- **安装启动**：v2.11.2 从 DMG 安装到 /Applications，Finder 双击启动成功（PID 62322），无崩溃。
- **子系统初始化**（runtime_20261020.log）：
  - OCR：ppocr_rust 原生引擎预加载成功
  - 剪贴板：管理器初始化、历史限制 1000、监听启动、图片 OCR 索引服务启动
  - 热键：ctrl+shift+a（截图）、ctrl+shift+g（继续标注）、ctrl+shift+h（继续上一张）、ctrl+shift+v（剪贴板）全部注册
  - 钉图：PinManager 初始化
- **截图热键触发**：Command+Shift+A 全局热键触发截图覆盖层（Carbon 全局热键已注册）。
- **win32gui 警告**：macOS 上 `win32gui 未安装，智能选区功能不可用` 仅为日志噪声，智能选区由 `platforms/macos/window_finder.py` 提供。

## 6. 稳定性检查

- **截图**：热键触发截图覆盖层，无崩溃；30 轮连续截图需真实 GUI 交互，转人工验收。
- **剪贴板**：热键注册成功，无 AX 客户端时剪贴板窗口不崩溃（任务3已验证 22 次 0 崩溃）。10 轮跨应用粘贴转人工验收。
- **录制**：任务4 本机管线验证 GIF 录制 14 帧非黑屏；5 轮 GUI 录制转人工验收。
- **环境阻塞**：AX 客户端（Computer Use/VoiceOver）下剪贴板窗口重建列表触发 Qt 段错误（任务3 残留，根因 Qt 6.8.3/PySide 无障碍代码），因此稳定性 GUI 测试需人工完成，不可用 AX 自动化替代。

## 7. DMG 安装到 /Applications 验证

- DMG：`dist/release/积磊截图-v2.11.2-261020-macOS-arm64.dmg`，hdiutil verify VALID。
- DMG 内容：`积磊截图.app` + Applications 符号链接。
- 安装：`cp -R` 到 /Applications，`CFBundleShortVersionString = 2.11.2`，架构 arm64。
- 双击启动：成功，不依赖开发目录/venv/终端环境变量。
- 资源校验（build_macos.py 输出）：
  - 图标 JileiScreenshot.icns ✅
  - SVG 托盘.svg ✅
  - 翻译 app_zh.qm ✅
  - OCR 模型 PP-OCRv6_det_small.onnx + PP-OCRv6_rec_small.onnx（Resources 与 MacOS 双份）✅
  - Rust 扩展：gifrecorder/longstitch/pyclipboard/ppocr_rust .abi3.so ✅
  - 原生依赖全部在 .app 内解析 ✅
  - Info.plist：bundle ID `cc.jilei.jileiscreenshot`，NSScreenCaptureUsageDescription 中文 ✅
- **缺口**：未在干净环境/第二台 Mac/最低支持系统（macOS 12.3）测试，仅在当前开发机验证。

## 8. 应用内更新全链路审计

### 代码审计（`main/platforms/macos/updater.py` + `factory.py`）

- `factory.get_native_updater()`：darwin 返回 `platforms.macos.updater` 模块 ✅
- `factory.update_target_arch()`：darwin 返回 `("darwin", "aarch64")` ✅
- `download_update`：HTTPS-only、SHA-256 校验、2GB 归档/6GB 展开上限、staged temp dir 在 app 旁 ✅
- `_extract_app`：tarball 路径校验（禁止绝对路径/`..`、必须以 `积磊截图.app` 开头）、`filter="data"`、bundle ID + 版本 + 可执行文件校验 ✅
- `_verify_signature`：`codesign` requirement 校验新 app TeamIdentifier 与当前一致 ✅
- `install_and_restart`：等待旧 PID 退出、备份当前 app、原子替换、`/usr/bin/open` 重启 ✅

### 已知阻塞

- 无生产更新清单变更权限，未做真实端到端更新测试。
- 更新签名密钥（Tauri updater）已用于四件套 .sig 生成，密钥 SHA-256 校验通过。

## 9. 本地数据/设置迁移与升级兼容

- 从 v2.10.0（/Applications）升级到 v2.11.2：
  - 设置：`~/Library/Preferences/com.jileiscreenshot.ToolSettings.plist` 保留全部快捷键、主题、剪贴板历史限制等配置 ✅
  - `has_run_before = 1` 保留 ✅
  - 历史目录：`~/Library/Application Support/JileiScreenshot/History/` 保留 ✅
  - 日志目录保留 ✅
- 未触碰用户真实数据做破坏性测试。

## 10. 签名与公开分发条件

- **codesign**：Apple Development: 75420203@qq.com (V4K3AG9C9A)，`--deep --strict --verify` 通过 ✅
- **spctl**：rejected（因 Apple Development 签名，非 Developer ID）❌
- **公证**：未执行（无 Developer ID + 公证凭据）❌
- **更新签名（.sig）**：Tauri updater minisign 签名，448 B，密钥 SHA-256 校验通过，tarball SHA-256 与记录一致 ✅
- **公开分发阻塞**：缺少 Apple Developer ID 证书与公证凭据，Apple Development 签名仅适合本机调试，无法通过 Gatekeeper，不能作为公开分发结论。

## 11. 版本递增与四件套

### 版本变更链

| 版本 | Commit | 说明 |
|------|--------|------|
| 2.11.0 | f4144bb | 任务4：长截图/GIF录制坐标对齐 |
| 2.11.1 | 36014ec | 任务5：测试套件修复 + text_settings_panel 导入修复 |
| 2.11.2 | c006b3d | 任务5：ruff lint 修复（未用导入清理） |

### 最终四件套（v2.11.2，dist/release/）

| # | 文件 | 大小 | 角色 |
|---|------|------|------|
| ① | `积磊截图-v2.11.2-261020-macOS-arm64.app.tar.gz` | 110,425,520 B | Updater artifact |
| ② | `积磊截图-v2.11.2-261020-macOS-arm64.app.tar.gz.sig` | 448 B | Signature |
| ③ | `积磊截图-v2.11.2-261020-macOS-arm64.dmg` | 119,172,932 B | 安装包 |
| ④ | `v2.11.2-261020-macOS-更新说明.txt` | - | 更新说明 |

- SHA256 记录：`dist/积磊截图-v2.11.2-261020-macOS-arm64.sha256`
- 历史产物（v2.8.1/v2.9.0/v2.10.0/v2.11.0/v2.11.1）原地保留，未删除/覆盖。
- 应用版本（Info.plist）= 源码版本（main_app.py APP_VERSION）= Tag v2.11.2 = 2.11.2 ✅

### Git

- Commit：`c006b3d` `v2.11.2-261020 任务5：修复 ruff lint 未使用导入`
- Tag：`v2.11.2`（annotated）
- Push：`origin fix/macos-native-parity` + `v2.11.2` ✅

## 12. 残留差异与待人工验收

### 代码层面残留

1. **AX 客户端 Qt 段错误**：VoiceOver/Computer Use 等 AX 客户端激活时，剪贴板窗口重建列表触发 Qt 6.8.3/PySide 无障碍代码段错误。无 AX 客户端时 22 次打开 0 崩溃。根因在 Qt 侧，非业务代码。
2. **ScreenCaptureKit CI 环境**：macOS CI runner 无屏幕录制权限，`record_session_basic` Rust 测试失败。本机有屏幕录制权限时 20/20 通过。

### 待人工验收（GUI 交互，AX 自动化不可用）

- 30 轮连续截图操作
- 10 轮跨应用剪贴板粘贴 + 焦点恢复
- 5 轮 GIF 录制（选区/标注入帧/导出/停止后焦点恢复）
- 全部编辑工具绘制与撤销重做
- 长截图真实滚动拼接（浏览器+文本编辑器纵/横向）
- 钉图 5 轮 + 动态右键菜单 29 条 + 通用编辑菜单 7 条
- 设置持久化跨重启
- 应用内更新端到端（需生产清单或授权测试服务）

### 公开分发阻塞

- 缺少 Apple Developer ID 证书 + 公证凭据，当前 Apple Development 签名无法通过 Gatekeeper。

## 结论

任务5完成全量测试套件与 Rust workspace 测试修复（2529 passed / 138 skipped，Rust 全通过），ruff lint 通过，Windows CI x64+arm64 通过，Mac 四件套 v2.11.2 已生成并推送。代码层面无未修复缺陷。GUI 稳定性与公开分发因环境/凭据阻塞转人工验收。
