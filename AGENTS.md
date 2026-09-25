# 项目开发规则

## 项目信息

```text
项目名：jietuba（截图吧）
默认分支：master2
Windows 构建：
python build_with_ocr_onefile.py
Git 远端：
origin
```

- 纯 Python + PySide6 桌面截图工具，仅支持 Windows（x86_64 / ARM64），无 Mac 构建。
- 构建产物：`dist/jietuba_pp.exe`（onefile）+ `dist/models/`（OCR 模型）。
- 依赖安装：`pip install -r requirements.txt`（构建另需 `pyinstaller`，见 `requirements-dev.txt`）。
- 应用内"检查更新"读取 GitHub Releases 的 tag 并与本地版本比较（`main/core/update_checker.py`）。

## 1. 工作原则

- 默认直接在 `master2` 修改，除非用户明确要求创建分支。
- 先看相关代码和调用链，只修改本次任务。
- 保留已有功能和用户修改。
- 不做无关重构、依赖升级或清理。
- 纯文档修改不升级版本、不构建软件。

## 2. 不自动测试

除非用户明确要求，否则禁止主动执行：
- 单元 / 集成测试（`main/tests` 下的 pytest 套件）；
- UI / E2E；
- Computer Use；
- 自动启动软件做功能验收；
- 为验证反复测试和构建。

功能最终由用户人工测试。

## 3. 修改后必须构建真实软件

影响软件运行的修改完成后：
- 必须生成本轮最新真实软件；
- 当前电脑只负责 Windows 平台；
- 构建失败继续修复直到成功；
- 不使用旧产物；
- 不随意清理构建缓存。

# 版本规则

- 版本唯一源：`main/main_app.py` 中的 `APP_VERSION`，其他地方（关于页、欢迎向导）均从此导入，禁止在别处再人工维护版本号。
- 所有正式软件版本统一采用 Semantic Versioning：MAJOR.MINOR.PATCH。
- 必须始终使用三段式，例如 2.0.6，不使用 2.1 这种两段式版本。
- Bug 修复：PATCH +1，例如 2.0.6 → 2.0.7。
- 新增向下兼容的新功能或明显功能升级：MINOR +1，PATCH 归零，例如 2.0.6 → 2.1.0。
- 重大不兼容升级：MAJOR +1，MINOR/PATCH 归零，例如 2.8.4 → 3.0.0。
- 一个发布批次无论包含多少 Commit，只产生一个正式版本号。
- 普通开发 Commit 不自动修改版本号，仅在正式发布时确定并递增版本。
- Git Tag 统一使用 vX.Y.Z，例如 v2.0.7。
- 应用版本、安装包（exe）、GitHub Release、Git Tag 必须保持完全一致。

## 4. 发布

1. 完成修改；
2. 递增并同步版本（只改 `main/main_app.py` 的 `APP_VERSION`）；
3. 构建当前平台真实软件（`python build_with_ocr_onefile.py`）；
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

## 5. 正式发布

只有用户明确要求正式发布时执行。
在快速发布的基础上增加本项目实际需要的：
- GitHub Release：填写版本号、发布说明，附上 `dist/jietuba_pp.exe` 与 `dist/models/` 产物；
- 产物附 SHA-256 校验值与文件大小；
- 发布后用应用内"检查更新"确认能读到新版本（无需做功能测试）。

正式发布同样不自动做功能测试。

## 6. Git

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

## 7. 最终回复

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
