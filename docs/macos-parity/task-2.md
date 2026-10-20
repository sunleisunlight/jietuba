# 任务2报告：截图捕获 / 画布 / 标注 / 编辑 / 输出对齐

更新：2026-10-19（Asia/Shanghai）。版本 **v2.9.0**。分支 `fix/macos-native-parity`（不合回 main）。
真源：Windows 正式版 v2.8.0（Tag `v2.8.0` / `7c0d289475ee630a4102f2b7e36b9aa8e49bb54c`）。

## 1. 范围

以 Windows v2.8.0 为真源，对齐 macOS 的截图捕获、画布、全部标注工具、编辑操作与输出
（复制 / 另存 / PNG / JPG / BMP / WebP / PDF），覆盖工具子功能、快捷键、设置持久化、
Retina / 坐标问题。对应矩阵 184 条（任务=2）。

## 2. 核心架构改造（Retina / 坐标，本轮根因）

问题：macOS 双 4K（dpr=2.0），mss 只给逻辑点导致截图发糊、线宽/字号/选区单位与 Windows 不一致。
决策：**场景=物理像素、屏幕/窗口=point**（`platforms/base/coordinates.py` 既定方向）。
- `main/platforms/macos/capture.py`：改用 CGWindowListCreateImage(CGRectInfinite)，输出覆盖整个虚拟桌面的物理像素图像（双 4K 为 7680x2160）；新增 capture_window。
- `main/platforms/macos/coordinates.py`：重写物理像素↔point 映射。
- `main/canvas/view.py`：新增 `_apply_view_transform` / `apply_display_scale` / `display_scale`；保留 mousePress/Move/Release 路由。
- `main/ui/screenshot_window.py` / `mask_overlay.py` / `selection_overlay.py` / `magnifier.py`：会话几何、scale、overlay 与 View transform 绑定、鼠标穿透。
- `main/pin/pin_window.py`：初始 setGeometry 走 mapper.capture_rect_to_qt。

效果：线宽/字号/选区/标注单位与 Windows 完全一致，导出 / 马赛克 / 放大镜 / 钉图 / OCR 自然正确；
仅窗口几何、View transform、overlay 定位需显式转换。pixel=(point-bbox.topLeft)×dpr 经红色标记窗口实验确认。

## 3. 对齐成果

- **全部 10 个标注工具**：pen / rect / ellipse / arrow / highlighter / mosaic / spotlight / number / text / note，绘制与 Windows 一致（另有 cursor、eraser）。
- **工具专属子功能**：rect 圆角/线样式、arrow 单/双向、number 实心/空心样式、mosaic 四档粒度/像素化/模糊/框选/自由、text 背景/描边/阴影、note 背景、spotlight 暗度。
- **编辑操作**：撤销/重做（QUndoStack）、橡皮擦删除+undo、自动选中、跨工具选择、控制点编辑。
- **快捷键**：工具键 p/2/o/3/4/1/m/7/5/s（spotlight 默认空），全局 ctrl+shift+a 等。
- **输出**：复制到剪贴板、另存、PNG/JPG/BMP/WEBP/PDF；边框/阴影/圆角导出；中文空格路径、无权限目录返回 False。

## 4. 测试证据（自主测试，任务文件授权）

- **QTest 真实鼠标事件（cocoa 真实窗口）**：`build/qtest_all_tools.py` 10/10 工具绘制、撤销 10 次、重做 10 次、5 种格式导出全部成功；`/tmp/qtest_all_annotated.png` 肉眼确认。
- **专属设置**：`build/test_special.py` 12/12 通过。
- **真实 App**：真实拖选区成功（主屏 1598×1400、左屏 656×1302），尺寸标签物理像素正确，工具栏齐全。
- **程序化/隔离**：输出链路、样式、序号、快捷键、设置持久化（隔离 ini）、边框/阴影/圆角、钉图入口，均通过，日志在 build/。
- 关键 RPA 结论：cu.drag 在该 QGraphicsView 编辑态缺少连续 mouseMove 致形状≈0（工具限制），QTest 连续事件证明应用功能正常。
- 非应用问题：QTest.keyClicks 中文 cocoa ASSERT；测试脚本退出 HistoryWorker 线程警告（真实 App 有 shutdown 处理）。

## 5. 矩阵结果（184 条）

| 状态 | 数量 | 说明 |
|---|---|---|
| 对齐已实测 | 79 | 真实事件/QTest/真实 App/输出链路直接验证 |
| 原生等效已验证 | 3 | 代码级一致（arrow_size、save_path×2） |
| 已实现待实测 | 102 | 共享代码，部分取值/inapp 动作/对话框/操作绑定未逐一触发 |

混合 dpr（不同屏 dpr 不同）无设备，记环境阻塞；代码用主屏 dpr 统一因子。

## 6. 待人工实测重点

- 真机手感：截图→选区→各工具标注→撤销/重做→复制/保存→再截图的完整循环；设置关闭重开恢复。
- 已实现待实测项：inapp 动作（zoom/thumbnail/restore_last_region/toggle_toolbar 等）、对话框按钮、工具栏显隐排序、OCR/继续标注入口、窗口/全屏/区域三种截图入口。
- 钉图完整功能（PinCanvas 缩放 Retina 行为）归任务3，任务2 仅保证入口正确。

## 7. 交付物

- Mac 四件套：`dist/release/`（v2.9.0-261019）app.tar.gz / .sig / dmg / 更新说明；`.sha256` 在 dist/。
- 安装：`/Applications/积磊截图.app` = 2.9.0（arm64，codesign 有效，Apple Development；spctl rejected，未公证，正式分发需 Developer ID+公证）。
- 旧包 v2.8.1 四件套原地保留。

详见 [TEST_EVIDENCE.md](TEST_EVIDENCE.md)、[STATE.md](STATE.md)、[FEATURE_MATRIX.md](FEATURE_MATRIX.md)。
