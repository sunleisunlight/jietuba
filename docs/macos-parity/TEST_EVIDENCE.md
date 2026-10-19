# 任务证据（追加记录）

## T2-20261019：任务2 截图捕获/画布/标注/编辑/输出对齐（最新）

### 环境与坐标事实（决定测试口径）
- 两台 4K 显示器：主屏 U27V10R point(0,0,1920,1080)；左屏 U270CA point(-1920,0,1920,1080)；virtualGeometry QRect(-1920,0,3840,1080)。两屏 dpr=2.0，物理 3840x2160。
- mss 在 macOS 上 monitors bounds / grab 只给逻辑点（1920x1080，发糊），已排除；CGWindowListCreateImage(CGRectInfinite) 返回覆盖整个虚拟桌面的物理像素图像（双 4K 为 7680x2160）。
- 落地原则“场景=物理像素、屏幕/窗口=point”：线宽/字号/选区/标注单位与 Windows 一致；仅窗口几何、View transform、overlay 定位显式转换。早期红色标记窗口实验确认 pixel=(point-bbox.topLeft)×dpr。

### 真实 App 实测（v2.9.0）
- 启动真实 App（pid 25085）→ 菜单栏/托盘菜单触发全屏截图会话；CGWindowList 确认全屏窗口 id=6038 layer=8 bounds(-1920,0,3840,1080)。
- 真实拖拽选区成功：一次主屏 1598×1400、一次左屏 656×1302，尺寸标签显示物理像素（point×dpr）；底部橙色工具栏出现、工具按钮齐全。
- 选画笔/矩形后用 cu.drag 在画布内拖拽形状不可见——根因定位为 RPA 工具限制（合成事件在 down/up 之间缺少连续 mouseMove，形状尺寸≈0），非应用缺陷（见下 QTest 证据）。

### QTest 真实鼠标事件（关键证据，cocoa 平台真实窗口）
- `build/qtest_repro.py`：mousePress 与 mouseRelease 之间插入 12 个 mouseMove（间隔 6-8ms），矩形成功创建（RectItem sceneBoundingRect 587,587,1026,826），导出 1400×1200，导出图红色矩形边框清晰。
- `build/qtest_all_tools.py`：**10/10 工具绘制全部通过**（pen/rect/ellipse/arrow/highlighter/mosaic/spotlight/number/text/note）；随后撤销 10 次（items 15→5）、重做 10 次（5→15）；导出 3440×1760，PNG 514KB / JPG 504KB / BMP 18.16MB / WEBP 170KB / PDF 376KB 全部成功。
- `/tmp/qtest_all_annotated.png` 肉眼确认：画笔/矩形/椭圆/箭头/荧光笔/序号1/文字“Hello 世界”/note（目标框+箭头+“这是备注”）在正确物理像素位置，spotlight 压暗框外。日志 `/tmp/qtest_all.log`。

### 工具专属子功能（build/test_special.py，12/12 通过）
- rect.corner_radius=25（_corner_radius）、rect.line_style=dashed_dense（非 SolidLine）；
- arrow.arrow_style=double（_arrow_style）；
- number.style=hollow_bg（item.style）；
- mosaic.block_size=32、style=blur（smooth）、draw_mode=rect（fill_mode）；
- text 背景/描边/阴影开关（has_background/has_outline/has_shadow）；
- note 背景（has_background）；spotlight.opacity=0.45（SpotlightCurtain.opacity）。
- 日志 `/tmp/special.log`。

### 其他程序化/隔离证据（历史，日志在 build/）
- 输出链路：7680x2160→选区1600x1200→导出1600x1200；PNG/JPG/BMP/WEBP/PDF；中文空格路径 /tmp/截图测试；无写权限 /System 返回 False；剪贴板 1600x1200。
- 样式：红色/线宽10/透明0.5 → item pen #ff0000/alpha128/width10；虚线 dashed→CustomDashLine；序号递增 1,2,3；橡皮擦删除+undo。
- 工具快捷键：p/2/o/3/4/1/m/7/5/e/s 实测切换工具，spotlight 默认空；12 条全通过。
- 设置持久化：隔离 ini 多轮写入/读取一致（format/quality/save_enabled/save_path 等）。
- 边框/阴影/圆角：border20→1640x1240、shadow25→1650x1250；钉图创建入口几何（物理→point）正确。
- arrow_size：代码级确认 v2.8.0 与 Mac 均仅在 settings 定义、无任何工具/item 读取，箭头大小由 stroke_width 推导，两边一致。

### 两个非应用问题（不影响结论）
- QTest.keyClicks 输入中文在 cocoa 上触发 qasciikey.cpp ASSERT 直接 abort（无法 try/except）；测试改用直接 setPlainText 到真实 TextItem。
- 测试脚本末尾 “QThread: Destroyed while thread is still running”（HistoryWorker）；真实 App 走 main_app._on_about_toquit 的 shutdown_history_manager，测试脚本绕过才出现。
- note 门控：测试环境为游客（can_create_note=False），脚本 monkeypatch NoteTool._pass_note_gate=True（账号门控非任务2范围）。

### 任务2矩阵结果（184 条）
对齐已实测 79、原生等效已验证 3、已实现待实测 102（工具专属取值、inapp 动作、对话框/操作绑定等未逐一触发，功能最终由用户人工验收）。混合 dpr 无设备，记环境阻塞。

## T1-20261019-J：用户提供凭据后的复核（最新，覆盖旧阻塞结论）

- 用户明确指定桌面凭据目录，文件名检查确认包含 updater 私钥与口令文件，不含Apple Developer ID/p12。没有执行目录内安装脚本，没有把说明文件当成授权。路径、安全读取方式和两类签名的区别已写入AGENTS.md；秘密内容没有输出或入库。
- 对I批最新暂存archive静默加载口令并调用现有签名函数成功，生成448 bytes的同名.sig；使用 `sunget-tauri/src-tauri/tools/verify-updater-signature.mjs` 验证实际archive，固定公钥、key ID、包体签名及trusted comment验证全部通过，退出0。sig SHA256=`283631aaaa368e4ff7a1e3c5c296a30ec72d90078a88ef0accdc23fe27f3d6c9`。archive/DMG/notes SHA256与I批完全一致，四文件齐于`dist/macos-release-sz88t8x3/`，未封版或移入release，旧产物均保留。
- CI39170509042精确SHA=`c7e78a38fa304a6d38e6ac88c7d0d7d64e56e0b9`；Windows x64/ARM64 job成功并产出真实exe。下载x64到`build/task1-windows-c7e78a3-x64/`；manifest版本2.8.2，exe为75,676,641 bytes，SHA256=`0cf5a189cb97110116940103491d430f215fab7fa21422e4f12380fc0ee6ed2b`，本地核对一致。CArchiveReader只读检查确认QtNetwork.pyd、Qt6Network.dll存在，PYZ含comtypes.shelllink和comtypes.persist。没有在Mac执行exe，不等于Windows UI验收。
- 同跑次Mac job失败：ppocr_rust构建时报`could not find native static library onnxruntime`、`can't do xcframework linking for target aarch64-apple-darwin`。不得把Windows子job成功说成整条CI通过。
- 全量39169825988的两个Windows job均失败：双击确认2项、README目录树3项、text_settings_panel的BACKGROUND_PRESET_STYLES导入1项。没有删除/跳过这些测试，也没有覆盖本地README草稿；双击/文字归任务2、文档全量归任务5，是否由任务1引入仍须源码归因。
- Computer Use只读进入系统设置→隐私与安全性→辅助功能，积磊截图.app开关为on；返回再进入输入监控，同名开关也为on。没有改动任何授权、添加/删除条目或修改其他App。此证据只证明系统UI状态，不能替代当前App内权限查询和授权后恢复截图。
- `/Applications/积磊截图.app` PID13381、设置显示v2.8.2；自动化AX/坐标点击导航会改变选中项，但右侧仍停留快捷键设置，键盘激活也未切换。尚未区分Qt AX执行语义和真实导航故障，不计权限页刷新通过。没有点击应用/重置、没有更改用户ctrl+shift+a与Cmd+2快捷键。可恢复自启测试已获用户同意，但尚未执行；没有更改LaunchAgent。
- 本批只修改文档与生成既有候选签名，不改运行代码，不重新构建，不递增版本或伪造完成Tag。任务1仍未通过；公开分发仍缺Developer ID/公证条件，真实入口循环与首次配置等继续待验。

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

## T1-20261019-F：继续执行，Windows失败诊断

- 再次fetch成功；origin/main仍为a26380ea80f73af029e7fc5f0ada65584fa1ef92，没有更新基线。保留三个README草稿、graphify-out-main和旧worktree。
- 原PID59837已退出；按可执行路径复核未见运行的JileiScreenshot。未由Agent终止进程。
- 旧安装2.8.1主程序SHA256为53f83d98ac604a75f0fb74a79a3163b1b9d30015c6dbd42eaffac875a3787ea7。
- 已创建可恢复安装备份 `dist/task1-install-backup-4BgqPj/积磊截图-v2.8.1-installed.zip`；SHA256为8538dea2f09c4bbe7fba61037dc3d129812f206d677c6025c0fbd1d2eabb6fae；ditto/unzip完整性检查退出0。尚未替换安装；没有读取或清空用户配置/历史。
- 两个签名口令环境入口仍未设置；只检查布尔存在性，没有尝试口令、读取私钥或输出秘密。
- CI39166063824完成失败：x64/arm64各142项收集，134通过、7平台跳过、1失败、0错误；唯一失败均为 `TestWindowsIntegration.test_desktop_shortcut_migrated`。新生命周期17项中14通过/3 Mac专属跳过；Rust步骤成功。Windows exe构建被跳过，macOS依赖job也跳过。
- 原始JUnit分别在 `build/task1-ci-39166063824-x64/`、`build/task1-ci-39166063824-arm64/`；迁移测试原先只断言False，业务日志未初始化，缺少原生失败原因。未删测试或改断言，增加捕获诊断（纯测试提交f86561af313ab6ec6b426d69af1d9ae3d3fb9e06），已push并核对远端。
- 诊断CI39167158457指向上述精确提交，仍使用同一任务1门禁。App运行代码未变化，dist中候选主程序SHA仍与E批一致。Mac该模块15通过/3 Windows专属跳过，ruff退出0；不能替代Windows失败复测。
- 诊断CI39167158457同样失败；已明确PowerShell/COM返回System.IO.FileNotFoundException，但pytest截断了CLIXML中间正文。再将诊断改为pytest.fail完整文本（纯测试提交e889cf7，已推送），CI39167821484取完整原因；未放宽断言、未跳过迁移。

## T1-20261019-G：正式Windows 2.8.0文件证据与清单补漏

- cc.jilei.cc公开更新接口恢复HTTP200，清单存于 `build/task1-windows-v2.8.0-manifest.json`。version=2.8.0，发布时间2026-10-18T18:54:09.114961+00:00；Tag与新增功能详情见BASELINE.md。此发现更正仅凭origin/main=2.7.0推断最新正式版本的旧记录。
- 正式exe下载到 `build/task1-windows-v2.8.0.exe`。首次curl因120秒上限退出28，保留47,775,744字节部分文件；随后对同一HTTPS地址Range续传退出0，不把部分文件计作成功。
- 完整文件70,483,525字节，SHA256=867e7a10492b03af2c13ec0d6c902b66ea0ef3f1046da89d940bac25db68908f，与公开清单一致；file报告PE32+ GUI x86-64。
- 只读PyInstaller归档检查：含python311.dll；反汇编打包main_app（不执行）得到LOAD_CONST '2.8.0' → STORE_NAME APP_VERSION。一次额外读取归档私有属性的检查以AttributeError退出1，改用实际TOC检查后退出0；不属于软件运行失败。
- 没有在Mac执行exe；未证明全部打包字节与Tag精确SHA的构建对应，未代替候选Windows测试/真实exe门禁。没有访问管理接口或修改线上清单。
- 菜单源码复核补充29条controller动态菜单、7条Qt通用编辑菜单；另登记v2.8.0的8条新增/变更操作，共744行。Graphify仅帮助定位，动态规则由直接源码审查发现；未重建图谱或执行任务2/3。

## T1-20261019-H：Windows前置修复与最新Mac候选（替代E批产物）

- CI39167821484完整错误：设置WScript的TargetPath时报ArgumentException，Save目标变为`Desktop/????.lnk`并报FileNotFoundException。两个Windows架构都失败，真实exe步骤跳过。
- 修复提交98a1cbc75681d537e4ff57c621b6f27344165f9e：经factory调用WindowsLifecycleBackend，复用既有comtypes.shelllink.IShellLinkW及IPersistFile；原生代码不再位于业务/UI。微软Unicode接口说明：https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ishelllinkw-setpath 。没有新增/升级依赖，不使用win32com/pythoncom或PowerShell执行策略绕行。
- Windows onefile原排除了PySide6.QtNetwork，而InstanceBroker依赖它；已移除排除并显式收集QtNetwork/comtypes.shelllink/comtypes.persist，增加静态契约与原生Unicode路径回读测试。
- 局部5模块52通过/6平台跳过；随后完整任务1的11模块188通过/6 Windows专属跳过，0失败/错误，runner退出0。JUnit `build/test-reports/run-l0zqrhdt/`；日志 `build/task1-resumed-final-tests.log`。ruff main+Windows构建脚本退出0。
- `.venv/bin/python build_macos.py`退出0，日志 `build/task1-shortcut-fix-build.log`。版本仍2.8.2未封版；Apple Development签名，未公证。主程序SHA256：ca7ea9337fcf25a9722793c3f3da4354afca9c7aa785bc105a5cc7c6870bae36。
- 对此真实App运行 `scripts/make_release_bundle.py --notes-file docs/releases/v2.8.2-macos.md`：归档/DMG成功，DMG CRC32=680DEEA8；签名入口检查因缺少环境口令退出1（没有再尝试空口令）。日志 `build/task1-resumed-final-bundle.log`，暂存 `dist/macos-release-u4oz6qdm/`，无有效.sig，不是四件套。此前调试目录全部保留。
- 最新archive SHA256=df762df684afdf7aca607085b1bd2b3fe9ad8dbfc96fa6aa3b4e51d1014c2b34；DMG SHA256=53a616ca96da56e50e6e708c0cd24093b8a0d028b7adb3e88c62737d0ca828b1；notes SHA256=d3a51f396f6ebfac79a4265558b664334bc03dd54bbf0cb8c6d9b224a235e7d6。
- DMG只读挂载到本轮临时目录，codesign deep strict、版本2.8.2、主程序hash与dist一致，随后卸载本轮挂载，退出0。用户旧挂载未动。
- 提交已push且ls-remote匹配；修复后Windows CI39168681792精确指向98a1cbc，等待原生测试/真实exe结果。无Tag、无main合并、无生产发布。

## T1-20261019-I：Windows 门禁闭环与 macOS QtNetwork 修复

- CI39168681792 的 x64/arm64 均完成成功；每架构任务1定向 JUnit 144 项，137 通过、7 个 Windows/macOS 平台跳过、0 失败/错误；两架构均完成真实 onefile 构建并上传。x64 manifest 位于 `build/task1-windows-98a1cbc-x64/build-manifest.json`，源码 `98a1cbc75681d537e4ff57c621b6f27344165f9e`，版本2.8.2，exe 74,547,495 bytes，SHA256 `0abba07c7c7142200a5dc264659da2c67642c1fe50cdae2d48faaf324e525272`。
- 对 x64 归档只读检查发现原 Windows whitelist 漏掉实际 QtNetwork DLL/pyd；因此不能把该 exe 当作可运行候选。修复提交 `c7e78a3` 将 `qt6network.dll`/`qtnetwork.pyd` 纳入 whitelist，并将 macOS spec 的 QtNetwork 从 excludes 移到 hiddenimports；新增静态契约断言。该提交已 push，CI39169825988 正在重新验证，旧 run 不冒充修复后产物。
- 旧 macOS 候选首次 Finder 双击日志明确报 `No module named 'PySide6.QtNetwork'`，退出码256；不是权限拒绝。修复后重新 `build_macos.py` 成功，安装 `/Applications/积磊截图.app` 的候选为2.8.2，主程序 SHA256 `cb6e449aeb5d0b6535b7ea419a9dcd15cc2ee3370d0a258e250e4b74bff21879`。通过终端启动后进程 `78203` 持续运行，Settings 窗口 AX 树可读，日志无未处理 Python 异常；Finder 双击/重复打开/退出重开仍待用户确认后执行。
- 安装替换前旧2.8.1与上一轮候选均已移入 `dist/task1-install-backup-4BgqPj/`，用户配置、历史、TCC、LaunchAgent未改动。签名/公证和 `.sig` 仍未完成。
- 补充26项macOS打包契约测试全部通过（含QtNetwork hiddenimports/excludes检查）。Windows PYZ只读检查确认comtypes.shelllink与comtypes.persist存在；缺失的是被binary whitelist过滤的QtNetwork.pyd/Qt6Network.dll。
- CI39168681792整体失败，失败在macOS Rust录制的record_session_basic（frame_count=0）及record_session_pause_resume（恢复后应有新帧），17通过/2失败，退出101；不改为跳过、不以本机19通过替代该runner结果。CI39169825988触发时未传parity_task1，因此是完整流程；另触发39170509042明确parity_task1=true，两者均指向c7e78a38fa304a6d38e6ac88c7d0d7d64e56e0b9。
- 真实设置页导航：AX click首次只改变选中态，按截图坐标点击后页面实际切换，显示屏幕录制已授权、辅助功能/输入监控未授权；刷新未改变状态，没有点击系统授权按钮。关闭设置后AX返回noWindowsAvailable，PID78203仍存活。Dock接口timeoutReached，不能计Dock reopen通过。Finder曾返回已移动备份的旧URL，未双击该条目。
- 最新归档/DMG通过现有脚本重新生成，暂存`dist/macos-release-sz88t8x3/`；DMG CRC32 F7DFC405。archive SHA256=b2ee26248961949c6e6679e989774663dd9f02e5d504800ebb790a82fe0fbec9；DMG SHA256=733dc54e8020a324fbd6acd1471439b5328f39b50f0cbc99f98711173830c43e；notes SHA256=d3a51f396f6ebfac79a4265558b664334bc03dd54bbf0cb8c6d9b224a235e7d6。签名在缺少环境口令处退出1，没有尝试空口令。日志build/task1-qt-network-bundle.log；旧release全部保留。
