# 任务证据（追加记录）

## T1-20261019-A：初始审计与复现

环境：macOS26.5 arm64；项目Python3.11.16；PySide6/Qt6.8.3。工作目录见STATE.md。源码起点c788d19，候选2.8.2工作区。原始用户日志/进程采样不提交Git。

| 检查 | 预期 | 实际/退出码 | 本地证据 |
|---|---|---|---|
| Git状态/fetch/worktrees | 保留草稿、核实新基线 | fetch 0；origin/main=a26380e | BASELINE.md |
| 旧App源码与日志 | 定位启动设置错误 | 日志有windll AttributeError与自启os NameError | ~/Library/Application Support/JileiScreenshot/Logs/runtime_20261019.log（仅本地） |
| 四个Rust扩展import | 全可导入 | 第一次/原样重建后gifrecorder均ImportError：___isPlatformVersionAtLeast，退出1 | 本轮工具输出；未视为通过 |
| 旧App Computer Use | 取得窗口/菜单 | 2次 getApp(/Applications/积磊截图.app) -10005 timeout；Dock同样超时；Finder正常 | 当前聊天工具记录，无可用App截图 |
| 旧App采样1秒 | 只读定位、不得kill | PID59837，2.8.1，主线程Qt/Cocoa事件循环等待，不是已证实死锁；退出0 | build/task1-old-process.sample.txt，不提交 |

## T1-20261019-B：针对性测试与原生修复

所有Qt测试使用 `QT_QPA_PLATFORM=cocoa`。真实用户TCC/LaunchAgent未更改；QSettings/注册测试在隔离路径。

- 首轮生命周期：15通过/1 Windows专属跳过，0失败，0.62s。
- 权限/工厂/隔离/打包契约：39通过/1跳过，0失败，0.36s。
- settings_dialog_state：57通过，0失败，0.24s；capture_settings_ui：29通过，0失败，4.73s。
- 11模块进程隔离总运行：`QT_QPA_PLATFORM=cocoa .venv/bin/python scripts/run_platform_tests.py --timeout 90 --module test_app_lifecycle.py --module test_macos_permissions.py --module test_platform_imports.py --module test_platform_factory.py --module test_settings_dialog_state.py --module test_capture_settings_ui.py --module test_about_update.py --module test_brand_migration.py --module test_macos_packaging_contract.py --module test_welcome_screenshot_page.py --module test_welcome_hotkey_page.py`。
- 结果：186通过、5跳过、0失败，runner退出0。JUnit逐模块耗时/结果在 `build/test-reports/run-d1fgc_6u/`。跳过仅Windows原生专属；不是Win回归通过。
- 新增旧版PID保护并消除Qt socket连接警告后，生命周期重跑：16通过/1跳过，0失败，0.66s。此结果替代上轮生命周期15通过；去重合计187通过、5跳过。新建锁、跨进程ACK、无响应不kill、过期锁、Cocoa delegate、启动模式、活动编辑路由有测试。
- Rust：`MACOSX_DEPLOYMENT_TARGET=12.3 PYO3_PYTHON=/Users/sunlei/codex/jietuba/.venv/bin/python cargo test --locked --manifest-path rust_libs/Cargo.toml -p gifrecorder --lib`；19通过、0失败，执行0.71s/含编译6.26s，退出0。不等于SCK真实录制。
- 原生wheel用maturin按12.3目标重建，安装本项目venv后四扩展均import成功；不升级依赖/系统Python。wheel在 `dist/task1-native-wheels/`。
- ruff全main + runner/inventory：退出0。为解除既有Windows lint门禁只删除9处未使用导入/变量，不改相关业务。

## T1-20261019-C：真实Mac构建，签名阻塞

执行项目 `scripts/make_release_bundle.py --build --notes-file docs/releases/v2.8.2-macos.md`（私钥通过现有路径，未打印内容）。本轮没有可用口令环境；一次空口令尝试被拒，未继续猜测。

- build_macos.py成功：2.8.2 / arm64；四原生扩展、双OCR模型、品牌资源、Bundle ID、版本键、动态依赖校验成功；codesign --verify --deep --strict通过。
- Apple Development签名；spctl rejected。没有Developer ID公证，不是公开分发成功。
- DMG hdiutil verify成功，CRC32 B539EE70。
- 外层release脚本退出1：`incorrect updater private key password: Wrong password for that key`。未生成有效.sig，未写release四件套。
- 暂存 `dist/macos-release-ujgi7u90/` 保留。没有安装/启动本轮包，没有把旧包UI结果套用到新包。

| 对象 | SHA-256 |
|---|---|
| dist/积磊截图.app/Contents/MacOS/JileiScreenshot | 71ca260f7d553b738299e9ea9f549e233fd6dc1fffabf835992e4b23809f9472 |
| 暂存2.8.2 app.tar.gz | a9707e317bf461306d2fdd74ab1bc9be55c2fd5cfbe0e8085ab3540a39051352 |
| 暂存2.8.2 DMG | ae436bdbf39fc03d072c0a5d18abaf7ed819b32880686e04619ec4c92968dd32 |

Windows候选CI、源码Commit、Tag/远端引用在后续批次追加。Finder三轮/重复打开三轮/退出重开三轮/区域截图/真实首次运行/真实权限/实际登录均未验收，不计通过。

## T1-20261019-D：最终候选复测（覆盖C的候选产物）

- 复核内部身份：QApplication.applicationName保持JileiScreenshot，displayName为积磊截图，避免QStandardPaths派生域漂移。
- 同一11模块最终重跑：187通过、5 Windows专属跳过、0失败/错误；合计测试耗时10.28s，runner退出0；`build/task1-final-tests.log` 与 `build/test-reports/run-xy358l3b/`。
- `.venv/bin/python build_macos.py` 最终构建退出0；`build/task1-final-build.log`。二进制SHA256 `1cc4b1f507e35d8be35ab64cd1bc728ac01b82e3f803b3b8a10c216643149ee2`。
- 使用已构建App再次生成暂存归档/DMG，不再猜测口令；脚本在已知缺少环境凭据入口处退出1，见 `build/task1-final-bundle.log`。最新目录 `dist/macos-release-i22urk_u/`；DMG CRC32 `6CA41DEB` 校验成功，仍缺.sig。
- C批次 `macos-release-ujgi7u90` 保留作为失败调试证据，**不是最新候选**；不得继续签名/发布旧暂存文件。
- 可选YAML本地解析检查未执行成功：项目venv无PyYAML（ModuleNotFoundError），未为此安装新依赖；以GitHub工作流实际解析结果为准。
- 安全凭据检查仅查看`.tauri`文件名与已有签名脚本的入口，确认均要求环境口令；未读取私钥内容或搜寻秘密。

## T1-20261019-E：候选追溯与包体复核

- 候选源码Commit `c5ac3985a90a75d89a8faa2aabcebf6d4fe34372`，已push origin/fix/macos-native-parity；`git ls-remote`匹配。v2.8.2 tag尚不存在。
- `gh workflow run ci.yml --ref fix/macos-native-parity -f parity_task1=true` 返回run `39166063824`。GitHub已解析新增输入；x64/arm64运行中。未取得exe，不记录为通过；不是完整Windows交互验收。
- 最终archive SHA256：`941e039d4fd980ab5fd94077c6e618a3a3fa1e5b9ca0a5cfe4e0923e00aa739b`；最终DMG SHA256：`bc86d33a22a3e6f5be520f42395339e7be2f9e8a3c1b99a8c0a3acb81f1fabe8`。
- 归档读取校验：Bundle ID、版本2.8.2、主程序hash与dist最终App一致，退出0。
- DMG只读挂载到本轮mktemp目录，验证包签名/版本/主程序hash一致，随后只卸载该测试挂载，退出0。未安装/启动；不碰用户此前挂载的旧DMG。
- 使用隔离Python导入最终App/Contents/Frameworks下四个.so均成功（gifrecorder/longstitch/pyclipboard/ppocr_rust）。这是原生加载检查，不是App权限身份或OCR/录制功能验证。
- 旧App日志/采样是2.8.1证据，绝不计作候选2.8.2截图/权限成功。旧进程未强杀。
