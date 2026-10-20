# -*- coding: utf-8 -*-
"""
帧采集控制器 — 全 Rust 架构 (gifrecorder)

录制：Rust 线程 抓屏（Windows BitBlt / macOS ScreenCaptureKit）→ JPEG 压缩 → FrameStore 存储
      Python 侧仅 QTimer tick 通知 UI 帧数，完全不碰像素

坐标系（与静态截图一致）：
  录制区域由 GifRecordWindow 以 **Qt 逻辑点（point）** 传入（窗口几何单位）；
  Rust 侧在 macOS 用逻辑点定位 SCK sourceRect，同时要求输出帧为
  **物理像素**（point × dpr），因此 FrameStore 的宽高是物理像素，
  与 Windows（点即像素）行为一致。
  鼠标轨迹按同一套换算采集，导出时直接落在帧像素坐标系。

停止后：
  - _store: gifrecorder.FrameStore 实例（持有全部帧数据）
  - _frames: 每帧对应的 FrameData（含 elapsed_ms + 标注列表）

图像由 PlaybackEngine 通过 FrameStore.get_frame_rgb() / start_decoder() 解码。
"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, QRect, QThread, Signal

from core.logger import log_error, log_info, log_exception, T

try:
    import gifrecorder
    _gifrecorder_available = True
except ImportError:
    gifrecorder = None
    _gifrecorder_available = False


# ── 数据结构 ──────────────────────────────────────────

class RecordState(Enum):
    IDLE      = auto()
    RECORDING = auto()
    PAUSED    = auto()
    STOPPED   = auto()


@dataclass
class CursorSnapshot:
    """单帧的鼠标状态快照（屏幕绝对坐标 → 相对录制区域坐标）"""
    x: int               # 相对于录制区域左上角的 X
    y: int               # 相对于录制区域左上角的 Y
    press: int           # 按键状态：0=无，1=左键，2=右键
    visible: bool = True # 光标是否在录制区域内
    scroll: int   = 0    # 滚轮方向：0=无，1=向上，-1=向下


@dataclass
class FrameData:
    """单帧元数据（无图像，图像由 PlaybackEngine 按需从 FrameStore 解码）"""
    elapsed_ms: int              # 距录制开始的毫秒数
    width: int    = 0            # 录制区域原始宽度（偶数对齐后）
    height: int   = 0            # 录制区域原始高度（偶数对齐后）
    annotations: list = field(default_factory=list)
    cursor: Optional[CursorSnapshot] = None  # 鼠标状态（None = 未采集）


# ── 采集器 ──────────────────────────────────────────

class FrameRecorder(QObject):
    """
    以指定帧率采集屏幕，通过 gifrecorder.RecordSession (Rust) 驱动。

    架构：
      Rust 线程: 抓屏（BitBlt / ScreenCaptureKit）→ JPEG 压缩 → FrameStore
      Python 侧: QTimer tick 仅发信号通知 UI 帧数变化

    Python 完全不参与截屏和像素处理，零 GIL 争用。

    录制区域用 **Qt 逻辑点** 表达（与窗口几何同一坐标系）；录制开始
    时换算成平台原生坐标系（Windows 像素 / macOS CG 点）并把输出帧
    固定为物理像素，使 Retina 下的 GIF 与 Windows 同为全分辨率。
    """

    frame_captured = Signal(int)   # 当前总帧数
    state_changed  = Signal(str)   # "IDLE" / "RECORDING" / ...
    limit_reached  = Signal()      # 达到最大录制时长，自动触发停止
    stop_finished  = Signal()      # stop_async 完成后发射

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rect: QRect = QRect()
        self._fps: int = 16
        self._frames: List[FrameData] = []
        self._state = RecordState.IDLE

        # QTimer 仅用于通知 UI 帧数更新 + 检测超时
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._max_duration_s: int = 60   # 最大录制时长（秒），0 表示不限制
        self._start_time: float = 0.0
        self._pause_offset: float = 0.0
        self._pause_start: float = 0.0

        # gifrecorder 对象
        self._store = None            # gifrecorder.FrameStore
        self._session = None          # gifrecorder.RecordSession
        self._rec_width: int = 0
        self._rec_height: int = 0

        # 鼠标轨迹（录制期间每 tick 采集一次，坐标为帧像素）
        self._cursor_track: List[CursorSnapshot] = []
        self._rec_left: int = 0       # 录制区域屏幕左上角（物理像素）
        self._rec_top: int = 0
        self._capture_factor: float = 1.0  # 点 → 物理像素系数（Retina = dpr）

        # pynput 滚轮监听（录制期间启动，读取后清零）
        self._scroll_value: int = 0   # 0=无, 1=向上, -1=向下
        self._mouse_listener = None   # pynput.mouse.Listener

    # ── 属性 ──

    @property
    def state(self) -> RecordState:
        return self._state

    @property
    def frames(self) -> List[FrameData]:
        return self._frames

    @property
    def fps(self) -> int:
        return self._fps

    @property
    def store(self):
        """gifrecorder.FrameStore 实例（录制/回放/导出共享）"""
        return self._store

    @property
    def total_duration_ms(self) -> int:
        if self._store is not None:
            return self._store.total_duration_ms
        if not self._frames:
            return 0
        return self._frames[-1].elapsed_ms

    @property
    def rec_size(self):
        """录制分辨率 (width, height)"""
        return self._rec_width, self._rec_height

    # ── 配置 ──

    def set_rect(self, rect: QRect):
        """设置录制区域（Qt 逻辑点；macOS Retina 下由本类换算为物理像素输出）"""
        self._rect = QRect(rect)

    def set_fps(self, fps: int):
        self._fps = fps
        if self._state == RecordState.RECORDING:
            self._timer.setInterval(1000 // fps)

    # ── 生命周期 ──

    def start(self):
        """开始录制。Rust 线程抓屏（BitBlt / SCK）→ FrameStore。"""
        if self._state not in (RecordState.IDLE, RecordState.STOPPED):
            return
        self._frames.clear()
        self._store = None
        self._session = None

        if not _gifrecorder_available:
            log_error(T("gifrecorder 不可用，无法录制"), "GIF")
            return

        # 内缩 1 点（Windows 上 1 点 = 1 像素），避免录入选区边框线
        _INSET = 1
        pt_x = self._rect.x() + _INSET
        pt_y = self._rect.y() + _INSET
        pt_w = max(self._rect.width() - _INSET * 2, 2)
        pt_h = max(self._rect.height() - _INSET * 2, 2)

        from platforms import get_platform_backend
        mapper = get_platform_backend().coordinates
        factor = mapper.qt_to_capture_factor(pt_x, pt_y)

        # 物理像素区域：Retina 下点 → 像素（Windows factor=1，与旧行为一致）
        left_px, top_px = mapper.qt_point_to_capture(pt_x, pt_y)
        right_px, bottom_px = mapper.qt_point_to_capture(pt_x + pt_w, pt_y + pt_h)
        px_w = max(right_px - left_px, 2)
        px_h = max(bottom_px - top_px, 2)

        self._rec_width = px_w
        self._rec_height = px_h
        self._rec_left = left_px
        self._rec_top = top_px
        self._capture_factor = factor
        self._cursor_track.clear()

        # 创建 FrameStore（像素尺寸）
        try:
            self._store = gifrecorder.FrameStore(
                width=px_w,
                height=px_h,
                fps=self._fps,
                jpeg_quality=90,
            )
            self._store.set_state(gifrecorder.STATE_RECORDING)
        except Exception as e:
            log_error(T("FrameStore 创建失败: {e}", e=e), "GIF")
            self._store = None
            return

        # 启动 Rust 截屏会话（区域=点、输出=像素）
        try:
            self._session = gifrecorder.RecordSession(
                self._store, pt_x, pt_y, pt_w, pt_h, self._fps,
                px_w, px_h,
            )
        except Exception as e:
            log_error(T("RecordSession 启动失败: {e}", e=e), "GIF")
            self._store = None
            self._session = None
            return

        self._start_time = time.perf_counter()
        self._pause_offset = 0.0
        self._pause_start = 0.0

        self._state = RecordState.RECORDING
        self._timer.start(1000 // self._fps)
        self._start_scroll_listener()
        self.state_changed.emit(self._state.name)
        log_info(T(
            "录制开始: 区域 {pt_w}x{pt_h} 点 → 输出 {w}x{h} 像素 @ {fps}fps (dpr={factor})",
            pt_w=pt_w, pt_h=pt_h, w=px_w, h=px_h, fps=self._fps, factor=factor), "GIF")

    def pause(self):
        """暂停录制"""
        if self._state != RecordState.RECORDING:
            return
        self._timer.stop()
        self._pause_start = time.perf_counter()
        if self._session:
            self._session.pause()
        if self._store is not None:
            self._store.set_state(gifrecorder.STATE_PAUSED)
        self._state = RecordState.PAUSED
        self.state_changed.emit(self._state.name)

    def resume(self):
        """恢复录制"""
        if self._state != RecordState.PAUSED:
            return
        self._pause_offset += time.perf_counter() - self._pause_start
        self._pause_start = 0.0
        if self._session:
            self._session.resume()
        if self._store is not None:
            self._store.set_state(gifrecorder.STATE_RECORDING)
        self._state = RecordState.RECORDING
        self._timer.start(1000 // self._fps)
        self.state_changed.emit(self._state.name)

    def stop(self) -> List[FrameData]:
        """同步停止录制"""
        self._timer.stop()
        self._stop_session()
        if self._store is not None:
            self._store.set_state(gifrecorder.STATE_STOPPED)
        self._sync_frames_from_store()
        self._state = RecordState.STOPPED
        self.state_changed.emit(self._state.name)
        return self._frames

    def stop_async(self):
        """非阻塞停止录制。

        立即停止计时器，在 QThread 后台线程等待 Rust 截屏线程退出，
        完成后发射 ``stop_finished`` 信号。
        """
        if self._state not in (RecordState.RECORDING, RecordState.PAUSED):
            self.stop_finished.emit()
            return

        self._timer.stop()
        session = self._session
        self._session = None

        class _StopWorker(QObject):
            finished = Signal()
            def __init__(self, recorder, session):
                super().__init__()
                self._rec = recorder
                self._session = session
            def run(self):
                try:
                    if self._session is not None:
                        try:
                            self._session.stop()
                        except Exception as e:
                            log_error(T("RecordSession.stop 异常: {e}", e=e), "GIF")
                    if self._rec._store is not None:
                        self._rec._store.set_state(gifrecorder.STATE_STOPPED)
                    self._rec._sync_frames_from_store()
                    self._rec._state = RecordState.STOPPED
                except Exception as e:
                    log_error(T("StopWorker 异常: {e}", e=e), "GIF")
                    self._rec._state = RecordState.STOPPED
                finally:
                    self.finished.emit()

        self._stop_thread = QThread()
        self._stop_worker = _StopWorker(self, session)
        self._stop_worker.moveToThread(self._stop_thread)
        self._stop_thread.started.connect(self._stop_worker.run)
        self._stop_worker.finished.connect(self._on_stop_worker_done)
        self._stop_thread.start()

    def _on_stop_worker_done(self):
        """后台停止完成，主线程回调。"""
        self.state_changed.emit(self._state.name)
        self.stop_finished.emit()
        if self._stop_thread:
            self._stop_thread.quit()
            self._stop_thread.wait()
            self._stop_thread.deleteLater()
            self._stop_thread = None
        if self._stop_worker:
            self._stop_worker.deleteLater()
            self._stop_worker = None

    def reset(self):
        """重置录制器（主线程调用）。"""
        self._timer.stop()
        self._stop_session()

        if self._store is not None:
            self._store.clear()
        self._store = None

        self._frames.clear()
        self._state = RecordState.IDLE
        self.state_changed.emit(self._state.name)

    def reset_data(self):
        """仅释放数据（FrameStore + 帧列表），不碰 QTimer。

        适合在非主线程调用（如 close_all 后台清理线程）。
        """
        self._stop_session()

        if self._store is not None:
            self._store.clear()
        self._store = None

        self._frames.clear()
        self._state = RecordState.IDLE

    # ── 内部 ──

    def _stop_session(self):
        """停止 Rust 截屏会话（阻塞等待线程退出）。"""
        self._stop_scroll_listener()
        if self._session is not None:
            try:
                self._session.stop()
            except Exception as e:
                log_exception(e, T("停止 Rust 截屏会话"))
            self._session = None

    def _sync_frames_from_store(self):
        """从 FrameStore 同步帧时间戳到 _frames 列表，并绑定鼠标轨迹"""
        if self._store is None:
            return
        self._frames.clear()
        timestamps = self._store.frame_timestamps
        n_frames = len(timestamps)
        n_cursor = len(self._cursor_track)

        for i, ts in enumerate(timestamps):
            # 鼠标采样数可能和帧数不完全一致（QTimer vs Rust 线程），
            # 按比例映射或直接按索引对齐
            cursor = None
            if n_cursor > 0:
                ci = min(i, n_cursor - 1) if n_frames <= n_cursor else int(i * n_cursor / n_frames)
                cursor = self._cursor_track[ci]
            self._frames.append(FrameData(
                elapsed_ms=ts,
                width=self._rec_width,
                height=self._rec_height,
                cursor=cursor,
            ))

    def _tick(self):
        """QTimer 回调：通知 UI 帧数更新 + 采集鼠标状态"""
        count = self._store.frame_count if self._store else len(self._frames)

        # ── 采集鼠标位置和按键状态 ──
        self._sample_cursor()

        self.frame_captured.emit(count)

        # 超过最大时长 → 自动停止
        elapsed = time.perf_counter() - self._start_time - self._pause_offset
        if self._max_duration_s > 0 and elapsed >= self._max_duration_s:
            self._timer.stop()
            self.limit_reached.emit()

    # ── 鼠标采集 ──

    @staticmethod
    def _get_cursor_pos_px() -> Tuple[int, int]:
        """当前鼠标位置（截图物理像素坐标系，平台后端统一换算）。"""
        from platforms import get_platform_backend
        return get_platform_backend().coordinates.cursor_pos_capture()

    @staticmethod
    def _buttons_pressed() -> Tuple[bool, bool]:
        """当前指针左右键状态（平台后端：GetAsyncKeyState / CGEventSourceButtonState）。"""
        from platforms import get_platform_backend
        return get_platform_backend().input.pointer_buttons()

    def _start_scroll_listener(self):
        """启动 pynput 滚轮监听（后台线程）"""
        try:
            from pynput import mouse

            def _on_scroll(x, y, dx, dy):
                # dy>0=向上, dy<0=向下
                if dy > 0:
                    self._scroll_value = 1
                elif dy < 0:
                    self._scroll_value = -1

            self._mouse_listener = mouse.Listener(on_scroll=_on_scroll)
            self._mouse_listener.start()
        except Exception as e:
            log_error(T("pynput 滚轮监听启动失败: {e}", e=e), "GIF")
            self._mouse_listener = None

    def _stop_scroll_listener(self):
        """停止 pynput 滚轮监听"""
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception as e:
                log_exception(e, T("停止滚轮监听"))
            self._mouse_listener = None
        self._scroll_value = 0

    def _sample_cursor(self):
        """采集一次鼠标快照（坐标已是帧像素坐标系），追加到 _cursor_track"""
        try:
            sx, sy = self._get_cursor_pos_px()
            rx = sx - self._rec_left
            ry = sy - self._rec_top
            visible = (0 <= rx < self._rec_width and 0 <= ry < self._rec_height)
            # 左键优先，右键次之
            left_down, right_down = self._buttons_pressed()
            if left_down:
                press = 1
            elif right_down:
                press = 2
            else:
                press = 0
            # 读取滚轮状态并立即清零（每帧只保留一次）
            scroll = self._scroll_value
            self._scroll_value = 0
            self._cursor_track.append(CursorSnapshot(
                x=rx, y=ry, press=press, visible=visible, scroll=scroll,
            ))
        except Exception as e:
            log_exception(e, T("采集鼠标快照"))
 