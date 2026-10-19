# 任务4：滚动长截图、GIF/视频录制对齐（macOS）

状态：已完成开发 + 本机管线验证，待用户人工验收 GUI 交互。
版本：2.11.0（MINOR +1，录制/长截图坐标单位重大对齐）
分支：`fix/macos-native-parity`，未合回 main。
源码提交：见本轮 Commit；Tag `v2.11.0`。

## 一、问题诊断

macOS 上长截图与 GIF 录制存在**坐标系单位错乱**：截图场景是物理像素，
但录制窗口/长截图窗口直接把像素矩形当作 Qt 逻辑点几何。Retina(dpr=2) 下：
- 录制窗口是实际选区的 2 倍大；
- 输出帧分辨率减半、画面重复；
- 长截图用 `QScreen.grabWindow` 只拿到 1x 逻辑分辨率，画面模糊。

探针 `build/task4_units_probe.py` 复现：输入 800x600 px 选区，窗口实际为
808x608 pt（应为 408x308 pt）。

## 二、核心修复

### 1. 统一坐标约定
- 静态截图：`CGWindowListCreateImage(CGRectInfinite)` → 物理像素
  （双 4K = 7680x2160），bbox = point bbox × dpr。
- 场景 = 物理像素，CanvasView 缩放 1/dpr，"场景=像素、屏幕=点"。
- SCK `sourceRect` = CG 点，`conf.width/height` = 物理像素。
- `MacOSCoordinateMapper`：
  - `qt_to_capture_factor()` = 该点所在屏 dpr；
  - `reference_factor()` = 主屏 dpr（导出侧像素换算基准）。

### 2. GIF 录制单位链路
- `frame_recorder.start()`：把 `self._rect`（点）拆成 `pt_*`（传给 SCK
  定位 sourceRect）和 `px_*`（FrameStore/输出帧），用
  `mapper.qt_point_to_capture()` 换算。
- Rust `RecordSession::new/start`、`ScreenCapture::new` 新增
  `out_width, out_height` 参数；0 = 与区域 1:1，仅负数报错。
- ObjC shim `JTKStartCapture` 新增 outW/outH，`conf.width/height = outW/outH`；
  **不再排除自身窗口**（`excludingWindows:@[]`）让绘制标注入帧，
  与 Windows BitBlt 一致。
- 光标采集改用 `mapper.cursor_pos_capture()`（像素）+
  `backend.input.pointer_buttons()`；`playback_controller` 光标 sprite
  缩放乘以 `mapper.reference_factor()`。

### 3. 长截图捕获链路
- `scroll_window._do_capture` 改用 `CaptureService().capture_all_screens()`
  （物理像素全桌面）+ 按 `capture_rect_px` 裁剪，废弃 `QScreen.grabWindow`。
- 统一 `convertToFormat(RGBA8888)` + `RGBA` raw 读取，不再假设 BGRA。
- `ScrollCaptureWindow.__init__` 新增 `capture_rect_px`（物理像素）、
  `capture_rect`（点，窗口几何用）。
- 横向滚动改用 `backend.input.send_scroll(dx_lines=...)`。
- 鼠标穿透统一走 `backend.windows.set_window_click_through`；
  `set_window_exclude_from_capture` 走 backend（macOS no-op）。

### 4. 平台后端扩展
- 新增 `base/input.py`、`windows/input.py`、`macos/input.py`：
  `pointer_buttons()` + `send_scroll()`。
- `factory.py` 注入 `input` 子后端。
- `base/coordinates.py` 新增 `reference_factor()`。
- `windows/window.py` 的 `set_window_click_through` 增加
  `SetWindowPos(SWP_FRAMECHANGED)` 并补齐常量。

### 5. 清理业务层平台泄漏
`main/gif`、`main/stitch` 中已无 `sys.platform`/`ctypes`/`win32` 直接调用。

## 三、本机验证证据

### Rust 测试（gifrecorder）
```
20 passed; 0 failed
```
含新增 `invalid_region_or_output_size_is_rejected`（负数输出尺寸被拒、
0 回退为区域尺寸）。

### Python 回归
- `test_frame_recorder.py`：28 passed（含新增 `TestUnitConversion`：
  dpr=2 时点区域→像素输出、dpr=1 时点像素一致）。
- `test_macos_coordinates.py`：7 passed（含新增坐标往返闭环、
  `reference_factor`、`cursor_pos_capture`）。
- `test_capture_service.py`：1 passed / 5 skipped（Windows mss 路径
  加 `skipif(darwin)`，macOS 走 CGWindowList 后端）。
- 全量 gif/stitch/platform 套件：185 passed / 6 skipped。

### 真实管线（非 mock）
- **GIF 录制**：Retina dpr=2，区域 400x300 点 → 输出 800x600 像素；
  1.5s 捕获 14 帧；帧亮度 extrema=(0,255) 非黑屏；
  RGB 字节数 = 800×600×3 = 1,440,000 与尺寸一致。
- **长截图捕获**：`capture_all_screens()` 返回 7680x2160 物理像素
  全桌面（rect=-3840,0,7680,2160）；按 800x600 裁剪正确，max gray=255。

## 四、修改文件清单

新建：
- `main/platforms/base/input.py`
- `main/platforms/windows/input.py`
- `main/platforms/macos/input.py`

修改：
- `main/gif/frame_recorder.py`、`record_window.py`、`overlay.py`、
  `drawing_view.py`、`cursor_overlay.py`、`playback_controller.py`
- `main/stitch/scroll_window.py`
- `main/platforms/factory.py`、`base/coordinates.py`、`windows/window.py`
- `rust_libs/gifrecorder/native/sck_capture.m`、
  `src/capture/macos.rs`、`src/capture/windows.rs`、
  `src/recorder.rs`、`src/lib.rs`
- `main/main_app.py`（版本 2.10.0 → 2.11.0）
- 测试：`test_frame_recorder.py`、`test_macos_coordinates.py`、
  `test_capture_service.py`

## 五、Mac 四件套

`dist/release/`（旧版本四件套原地保留）：
- `积磊截图-v2.11.0-261020-macOS-arm64.app.tar.gz`（~110 MB）
- `积磊截图-v2.11.0-261020-macOS-arm64.app.tar.gz.sig`（448 B）
- `积磊截图-v2.11.0-261020-macOS-arm64.dmg`（~119 MB，hdiutil verify VALID）
- `v2.11.0-261020-macOS-更新说明.txt`

`.sha256` 在 `dist/`。签名用 `~/.tauri/sunget-updater-20260825.key`，
口令从 `SunGet-Windows-Updater-Key-20260825/sunget-updater-password.txt` 读取。
codesign = Apple Development（本机调试可用；公开分发需 Developer ID + 公证，
当前无凭据，记环境阻塞）。

## 六、待人工验收

以下需真实鼠标/GUI 交互，本机自动化无法覆盖：
1. 长截图：浏览器 + 文本编辑器各跑竖向/横向，检查接缝、缺行、重复行；
   至少取消/失败用例。
2. GIF：短录制(5s)、~60s、快速开始停止、取消导出、连续 5 次录制；
   解码检查多帧非黑屏、时序正确、标注入帧效果。
3. 录制停止后焦点/鼠标穿透/窗口层级恢复。
4. 回归任务1~3核心：启动/截图/热键/剪贴板/钉图基础。

## 七、残留与已知限制

- 公开分发阻塞：仅有 Apple Development 签名，无 Developer ID + 公证。
- 任务3 残留未在本任务处理：AX 客户端下剪贴板窗口 Qt 段错误（Qt 6.8.3
  无障碍代码）、`win32gui 未安装` 日志噪声。
