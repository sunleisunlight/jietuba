# 项目开发规则

本文件是 jietuba（截图吧）的 Agent 协作规范。任何 Agent 在本仓库工作前必须先完整阅读本文件，并遵守其中规则。
`README.md` / `README_zh-CN.md` / `README_JA.md` 是功能与使用文档，`AGENTS.md` 是开发与协作规则；两者冲突时以本文件为准。

## 项目信息

```text
项目名：jietuba（截图吧）
平台：Windows + macOS（同一套代码、同一个主开发分支）
默认分支：master2
Windows 构建：python build_with_ocr_onefile.py
macOS 构建：scripts/setup_macos.sh → python build_macos.py → scripts/package_macos.sh
macOS 目标：Apple Silicon(arm64) + macOS 12.3 及以上（GIF 录制依赖 ScreenCaptureKit，无低版本 fallback）
Python：仅支持 3.11（scripts/setup_macos.sh 会强制校验，Windows 用 venv311）
Git 远端：origin
```

- 技术栈：Python 3.11 + PySide6（Qt6）；性能核心为 Rust（PyO3 / maturin）：
  `rust_libs/gifrecorder`（GIF 录制）、`rust_libs/longstitch`（长截图拼接）、
  `rust_libs/pyclipboard`（剪贴板历史库）、`rust_libs/ppocr_rust`（PaddleOCR）。
- 构建产物：Windows `dist/jietuba_pp.exe`（onefile）+ `dist/models/`（OCR 模型）；
  macOS `.app` / `.dmg`。
- 依赖安装：`pip install -r requirements.txt`（构建 / 测试另需 `requirements-dev.txt`）。
- 应用内"检查更新"读取 GitHub Releases 的 tag 并与本地版本比较（`main/core/update_checker.py`）。

## 1. 架构边界（跨平台核心规则）

- **一套业务代码 + 一套平台接口 + 两套底层 backend**。UI、Canvas、标注、Note、文字、
  OCR、钉图、剪贴板业务逻辑、翻译、设置、数据模型、通用服务、通用工作流一律共享，
  不分平台维护两份业务代码。
- 只有真正依赖操作系统的能力才允许分平台，统一放在 `main/platforms/`：
  - `main/platforms/base/`：抽象接口（capture / window / accessibility / coordinates /
    hotkey / clipboard / permissions）。
  - `main/platforms/windows/`：Win32 / UIA / ctypes / pywin32 实现。
  - `main/platforms/macos/`：CGWindowList / AXUIElement / TCC / ScreenCaptureKit /
    Carbon / Cocoa 实现。
  - `main/platforms/factory.py`：业务代码只通过它获取当前平台 backend。
- 业务模块中禁止新增散落的 `if sys.platform == ...` / `ctypes.windll` / `win32gui` /
  `AXUIElement` / `CGWindowList` / `Carbon` 判断；平台判断集中在 factory / backend 层。
- Windows 与 macOS 各保留一份原生实现，互不劣化：不要为了"每行代码都一样"删除平台原生能力，
  也不要用一边的实现硬套另一边。

## 2. 工作原则

- 默认直接在 `master2` 修改，除非用户明确要求创建分支。
- 先看相关代码和调用链，只修改本次任务。
- 保留已有功能和用户修改。
- 不做无关重构、依赖升级或清理。
- 纯文档修改不升级版本、不构建软件。

## 3. 分支模型

- `master2` 是**唯一长期主线**，Windows 与 macOS 的正式改动最终都汇入 `master2`。
- **禁止长期维护 Windows / macOS 两条功能分叉的主线**。
- 大型改造（如跨平台重构）必须在独立分支（必要时用独立 worktree）进行，禁止直接污染 `master2`。
- 日常改动使用短期分支，完成后回合 `master2`：
  - 新功能：`feature/<name>`
  - Windows 问题：`fix/windows-<name>`
  - macOS 问题：`fix/macos-<name>`
- 禁止 `reset --hard` 覆盖现有工作、`force push`、覆盖已有 Tag、删除他人 worktree。

## 4. 不自动测试

默认不主动执行（除非用户明确要求）：
- 单元 / 集成测试（`main/tests` 下的 pytest 套件）；
- UI / E2E；
- Computer Use；
- 自动启动软件做功能验收；
- 为验证反复测试和构建。

用户明确要求验证时，可以执行与本次改动直接相关的测试与构建；功能最终仍由用户人工测试。

## 5. 修改后必须构建真实软件

影响软件运行的修改完成后：
- 必须生成本轮最新真实软件；
- 构建失败继续修复直到成功；
- 不使用旧产物冒充新构建；
- 不随意清理构建缓存。

各平台只负责构建本平台产物：当前 Windows 机器只构建 Windows exe，macOS 机器只构建 mac 包。

## 6. 环境与工具链

- Python：**3.11**（唯一支持的 Python 主版本）。开发使用项目虚拟环境，禁止污染系统 Python。
- Rust：`rustc` / `cargo` 需与项目工具链一致；构建扩展一律走 `maturin build`，产物为平台原生 wheel。
  - `cargo test` 前需设置 `PYO3_PYTHON` 指向项目 venv；pyo3 的 `extension-module` 是可选 feature，
    `cargo test` 不加该 feature，`maturin` 构建时启用。
- macOS 打包：`scripts/setup_macos.sh`（工具链 / venv / 依赖 / Rust wheels）→
  `build_macos.py`（PyInstaller onedir `.app` + 签名 + 验证）→
  `scripts/package_macos.sh`（DMG）；签名 / 公证见 `scripts/notarize_macos.sh` 与
  `packaging/entitlements.plist`。
- Windows 打包：`build_with_ocr_onefile.py`（PyInstaller onefile `.exe`）。

# 版本规则

- 版本唯一源：`main/main_app.py` 中的 `APP_VERSION`，其他地方（关于页、欢迎向导、macOS 打包）
  均从此导入，禁止在别处再人工维护版本号。
- macOS 打包链（`build_macos.py`、`jietuba_macos.spec`、`scripts/package_macos.sh`、
  `scripts/notarize_macos.sh`）统一通过 `scripts/version_utils.py`（`ast` 静态解析，
  不 import main_app.py 以避免副作用）读取 `APP_VERSION`；Info.plist 版本、DMG 文件名、
  公证脚本寻找的 DMG 全部由此派生，禁止在其中写死版本号。
- `pyproject.toml` 的 `project.version` 只是 Python 工程元数据，**不是** `APP_VERSION`，
  不参与正式发布版本。
- **Windows 与 macOS 共用同一个 `APP_VERSION`，同一次正式发布必须是同一个版本号。**
- 所有正式软件版本统一采用 Semantic Versioning：MAJOR.MINOR.PATCH。
- 必须始终使用三段式，例如 2.4.0，不使用 2.1 这种两段式版本。
- Bug 修复：PATCH +1，例如 2.0.6 → 2.0.7。
- 新增向下兼容的新功能或明显功能升级：MINOR +1，PATCH 归零，例如 2.0.6 → 2.1.0。
- 重大不兼容升级：MAJOR +1，MINOR/PATCH 归零，例如 2.8.4 → 3.0.0。
- 一个发布批次无论包含多少 Commit，只产生一个正式版本号。
- 普通开发 Commit 不自动修改版本号，仅在正式发布时确定并递增版本。
- Git Tag 统一使用 vX.Y.Z，例如 v2.0.7。
- 应用版本、安装包（Windows exe / macOS app+dmg）、GitHub Release、Git Tag 必须保持完全一致。

## 发布

1. 完成修改；
2. 递增并同步版本（只改 `main/main_app.py` 的 `APP_VERSION`）；
3. 构建当前平台真实软件；
4. Commit；
5. Tag；
6. Push（推送 `origin` 的 `master2` 分支与 Tag）；
7. 交给用户人工测试。

Commit：

```text
v<版本>-<YYMMDD> <中文摘要>
```

Tag：

```text
v<版本>-<YYMMDD>
```

Tag 默认使用 annotated tag。

## 正式发布

只有用户明确要求正式发布时执行。
在快速发布的基础上增加本项目实际需要的：
- GitHub Release：填写版本号、发布说明，附上 `dist/jietuba_pp.exe` 与 `dist/models/`（Windows），
  以及 macOS 的 `.app` / `.dmg` 产物；
- 产物附 SHA-256 校验值与文件大小；
- 发布后用应用内"检查更新"确认能读到新版本（无需做功能测试）。

正式发布同样不自动做功能测试。

## 测试与质量门

- 测试命令（仓库根）：`pytest main/tests -c main/tests/pytest.ini`。
  - macOS 上 Qt 测试使用 `QT_QPA_PLATFORM=cocoa`；Windows CI 使用 `offscreen`。
  - Windows 专属测试（WM_ 消息、UIA 控件树、CF_HDROP、Ctrl+Insert 语义、SetWindowPos 置顶等）
    必须加 `pytestmark = pytest.mark.skipif(sys.platform != "win32", ...)`，
    模块顶层的 Win32 常量访问也要做平台条件，不能只靠 skipif。
  - macOS 专属测试同理只在 macOS 运行。
- Rust 测试：`cargo test --workspace`（先设 `PYO3_PYTHON`）。
- 新增平台相关代码必须配套平台测试（参考 `main/tests/test_platform_imports.py`、
  `test_platform_factory.py`、`test_macos_coordinates.py`、`test_macos_permissions.py`）。
- 禁止用 `try: ... except: pass` 掩盖真实错误；禁止为通过测试直接删除测试。
- CI：`.github/workflows/ci.yml` 区分 Windows 与 macOS job；Windows-only / macOS-only 测试
  只在对应平台运行，共享业务测试尽量两平台都跑。

## Git

开始先检查：

```bash
git status --short --branch
```

默认：

```text
master2
```

发布推送所有项目要求的远端（当前为 `origin`）。
禁止：
- force push；
- 覆盖已有 Tag；
- 把无关文件混入本次 Commit。

## 最终回复

只需要告诉用户：
- 版本；
- 修改内容；
- 软件是否构建成功；
- 产物路径；
- Commit；
- Tag；
- Push 状态；
- 快速发布 / 正式发布；
- 需要人工测试的重点。

编译成功 ≠ 功能测试通过。
