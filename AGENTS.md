# AGENTS.md

本文件是 Jietuba 项目（Windows + macOS 跨平台截图工具）的 Agent 协作规范。
任何 Agent 在本仓库工作前必须先完整阅读本文件，并遵守其中规则。
README.md / README_zh-CN.md 为功能与使用文档，AGENTS.md 为开发与协作规则；
两者冲突时以 AGENTS.md 为准，本文件未覆盖之处遵循项目现有约定。

## 1. 项目概览

- Jietuba（截图吧）：桌面截图工具，功能覆盖截图、标注、OCR、钉图、长截图、
  GIF 录制、剪贴板历史、翻译等。
- 技术栈：Python 3.11 + PySide6（Qt6）；核心性能模块为 Rust（PyO3/maturin）：
  `rust_libs/gifrecorder`（GIF 录制）、`rust_libs/longstitch`（长截图拼接）、
  `rust_libs/pyclipboard`（剪贴板历史库）、`rust_libs/ppocr_rust`（PaddleOCR）。
- 目标架构：绝大多数 UI/业务逻辑共享，仅操作系统相关能力拆为平台后端
  `main/platforms/`（`base/` 抽象接口 + `windows/` + `macos/` 实现）。
  业务代码禁止散落 `if sys.platform == ...`，平台判断集中在 factory/backend 层。
- Windows 与 macOS 各保留一份原生实现（Win32/UIA/BitBlt 与 CGWindowList/
  AXUIElement/ScreenCaptureKit），互不劣化。

## 2. 仓库与分支

- 主开发分支：`master2`。所有正式改动最终汇入 `master2`。
- 大型改造（如跨平台）必须在独立分支/独立 worktree 进行：
  - 示例：`git worktree add ../jietuba-macos -b cross-platform-macos <base-commit>`
  - 禁止直接污染 `master2`；禁止 `reset --hard`、`force push`、覆盖他人 worktree。
- 远端：
  - GitHub：`origin`（`https://github.com/sunleisunlight/jietuba.git`）
  - NAS Gitea：`gitea`（`sunget-nas-git:sunget/jietuba.git`，SSH 端口 222）
- 推送新功能分支到远端时，保持分支名与本地一致，不做 force push。

## 3. 环境与工具链

- Python：**3.11**（项目唯一支持的 Python 主版本）。开发使用项目虚拟环境 `.venv`，
  禁止污染系统 Python。macOS 上请用 `.venv/bin/python`（不要用 PATH 上的其他版本）。
- Rust：`rustc`/`cargo` 需与项目 `rust-toolchain` 一致；构建 Rust 扩展一律走
  `maturin build`，产物为平台原生 wheel。
  - 注意：`cargo test` 前需设置 `PYO3_PYTHON` 指向项目 venv，否则链接到错误
    的 libpython 会失败；pyo3 的 `extension-module` 是可选 feature，
    `cargo test` 不加该 feature，maturin 构建时通过 `--features extension-module` 启用。
- macOS 打包：`scripts/setup_macos.sh`（准备工具链/venv/依赖/Rust wheels）→
  `build_macos.py`（PyInstaller onedir .app + 签名 + 验证）→
  `scripts/package_macos.sh`（DMG）。
- Windows 打包：`build_with_ocr_onefile.py`（PyInstaller onefile .exe），保留不动。

## 4. 测试与质量门

- 测试命令（仓库根）：`pytest main/tests -c main/tests/pytest.ini`。
  - macOS 上 Qt 测试使用 `QT_QPA_PLATFORM=cocoa`（`offscreen` 插件在 PySide6
    6.11 下不稳定会段错误）；Windows CI 使用 `offscreen`。
  - Windows 专属测试（WM_ 消息、UIA 控件树、CF_HDROP、Ctrl+Insert 语义、
    SetWindowPos 置顶等）必须加 `pytestmark = pytest.mark.skipif(sys.platform != "win32", ...)`，
    且模块顶层的 Win32 常量访问也要做平台条件，不能只靠 skipif。
- Rust 测试：`cargo test --workspace`（先设 `PYO3_PYTHON`）。
- 新增平台相关代码必须配套平台测试（参考 `main/tests/test_platform_imports.py`、
  `test_platform_factory.py`、`test_macos_coordinates.py`、`test_macos_permissions.py`）。
- 质量门：
  - 禁止用 `try: ... except: pass` 掩盖真实错误。
  - 新代码行覆盖率 PR 门槛 80%；总量棘轮 `--cov-fail-under=37`（只升不降）。
  - CI：`.github/workflows/ci.yml` 跑 Windows x64/arm64 + macOS 三套 job。

## 5. 版本规则（强制）

- 所有正式软件版本统一采用 Semantic Versioning：`MAJOR.MINOR.PATCH`。
- 必须始终使用三段式，例如 `0.19.0`，不使用 `0.19` 这种两段式版本。
- Bug 修复：`PATCH +1`，例如 `0.19.0 → 0.19.1`。
- 新增向下兼容的新功能或明显功能升级：`MINOR +1`，`PATCH` 归零，
  例如 `0.19.3 → 0.20.0`。
- 重大不兼容升级：`MAJOR +1`，`MINOR`/`PATCH` 归零，例如 `1.8.4 → 2.0.0`。
- 一个发布批次无论包含多少 Commit，只产生一个正式版本号。
- 普通开发 Commit 不自动修改版本号，仅在正式发布时确定并递增版本。
- Git Tag 统一使用 `vX.Y.Z`，例如 `v0.19.0`。
- 应用版本、安装包、更新元数据、控制中心、GitHub Release、Git Tag
  必须保持完全一致。
- 项目应维护**唯一版本源**，禁止多个位置人工分别维护版本号。
  版本号只在版本源处修改，其余位置通过构建/生成流程读取该唯一来源。

## 6. 提交与发布

- 提交信息使用 Conventional Commits：`feat:` / `fix:` / `build:` / `test:` /
  `docs:` / `refactor:` 等，附加范围如 `feat(macos): ...`。
- 按阶段/逻辑边界提交，不要每改一行提交一次，也不要一个巨型提交。
- 正式发布流程：
  1. 在唯一版本源递增版本号（遵守第 5 节规则）；
  2. 构建安装包并核对版本一致性（应用/安装包/更新元数据/控制中心）；
  3. 打 Tag `vX.Y.Z` 并推送（GitHub Release 与 Tag 必须一致）；
  4. 生成 GitHub Release 及更新元数据。
