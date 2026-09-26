# -*- coding: utf-8 -*-
"""macOS 控件级智能选区 — Accessibility (AXUIElement) 实现。

与 Windows UIAElementFinder 保持同一上层接口（elements_at /
request_refresh_if_needed / prewarm / close / cache_updated 信号）。

实现要点：
  - 句柄是 CGWindowID；扫描前先经 CGWindowListCopyWindowInfo 解析出
    所属应用 PID，再 AXUIElementCreateApplication(pid)；
  - 异步扫描（后台线程），结果回主线程发 cache_updated，不阻塞 UI；
  - 需要"辅助功能"权限；未授权时 is_macos_accessibility_available()
    返回 False，上层降级为纯窗口检测（普通截图不受影响）。
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from core import log_debug
from core.logger import T

from ..base.accessibility import AccessibilityBackend, ElementSnapshot
from .permissions import _ax_is_trusted


def is_macos_accessibility_available() -> bool:
    """AXUIElement 能力可用：本机 + 辅助功能已授权。"""
    try:
        return _ax_is_trusted()
    except Exception:
        return False


def _pid_for_window(window_id: int) -> Optional[int]:
    """从 CGWindowID 解析所属应用 PID（带小缓存）。"""
    _cache: Dict[int, int] = {}
    pid = _cache.get(window_id)
    if pid is not None:
        return pid
    try:
        import Quartz
        # 注意：kCGWindowListOptionIncludingWindow 必须配具体窗口 id；
        # 配 kCGNullWindowID 会返回空列表。这里用 OnScreenOnly 枚举全部
        # 前台窗口即可解析到任一可见窗口的 PID。
        info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID,
        )
        for win in info or []:
            if win.get("kCGWindowNumber") == window_id:
                owner_pid = win.get("kCGWindowOwnerPID")
                if owner_pid:
                    _cache[window_id] = int(owner_pid)
                    return int(owner_pid)
    except Exception:
        pass
    return None


def _ax_value(element, attribute):
    """AXUIElementCopyAttributeValue 封装（PyObjC）。"""
    try:
        import ApplicationServices
        return ApplicationServices.AXUIElementCopyAttributeValue(
            element, attribute, None
        )[1]
    except Exception:
        return None


def _ax_position_size(element):
    """返回 (x, y, width, height) 或 None（AX 坐标=屏幕全局点坐标，左上原点）。"""
    try:
        import ApplicationServices as AS
        position = _ax_value(element, AS.kAXPositionAttribute)
        size = _ax_value(element, AS.kAXSizeAttribute)
        if position is None or size is None:
            return None
        # PyObjC：AXValueGetValue 返回 (True, CGPoint/CGSize)，
        # 直接访问 .x/.y/.width/.height 会 AttributeError。
        ok_p, pt = AS.AXValueGetValue(position, AS.kAXValueCGPointType, None)
        ok_s, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
        if not (ok_p and ok_s):
            return None
        return float(pt.x), float(pt.y), float(sz.width), float(sz.height)
    except Exception:
        return None


def _scan_tree(element, out: list, depth: int, max_depth: int, max_elements: int) -> None:
    """递归收集所有带矩形控件的 ElementSnapshot（AXChildren 遍历）。"""
    if depth > max_depth or len(out) >= max_elements:
        return
    try:
        import ApplicationServices
        children = _ax_value(element, ApplicationServices.kAXChildrenAttribute)
        if not children:
            return
        for child in children:
            if len(out) >= max_elements:
                return
            try:
                role = _ax_value(child, ApplicationServices.kAXRoleAttribute) or ""
                # 跳过窗口角色本身与隐藏元素
                if role == ApplicationServices.kAXWindowRole:
                    continue
                visible = _ax_value(child, ApplicationServices.kAXRoleAttribute)
                if visible is None:
                    continue
                rect = _ax_position_size(child)
                if rect is not None:
                    x, y, w, h = rect
                    if w >= 2 and h >= 2:
                        out.append(ElementSnapshot(
                            (int(x), int(y), int(x + w), int(y + h)), order=len(out)
                        ))
                _scan_tree(child, out, depth + 1, max_depth, max_elements)
            except Exception:
                continue
    except Exception:
        return


class _MacScanWorker(threading.Thread):
    """单窗口后台扫描线程。"""

    def __init__(self, window_id: int, on_done):
        super().__init__(daemon=True)
        self._window_id = window_id
        self._on_done = on_done
        self._result: Optional[Tuple[ElementSnapshot, ...]] = None

    def run(self):
        try:
            pid = _pid_for_window(self._window_id)
            if pid is None:
                self._on_done(self._window_id, ())
                return
            import ApplicationServices

            app = ApplicationServices.AXUIElementCreateApplication(pid)
            if app is None:
                self._on_done(self._window_id, ())
                return
            windows = _ax_value(app, ApplicationServices.kAXWindowsAttribute)
            out: List[ElementSnapshot] = []
            for win in windows or []:
                _scan_tree(win, out, 0, 12, 4096)
            # 由细到粗：面积升序
            out.sort(key=lambda s: s.area)
            self._on_done(self._window_id, tuple(out))
        except Exception:
            self._on_done(self._window_id, ())


class MacAccessibilityElementFinder(QObject):
    """macOS 控件级元素查找器（接口对齐 UIAElementFinder）。"""

    cache_updated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshots: Dict[int, Tuple[ElementSnapshot, ...]] = {}
        self._pending: set = set()
        self._lock = threading.Lock()
        self._closed = False

    # ── 公共接口 ──

    def elements_at(self, hwnd: int, x: int, y: int, min_size=(1, 1)) -> Tuple[ElementSnapshot, ...]:
        """返回命中的控件矩形（由细到粗）。"""
        snapshots = self._snapshots.get(hwnd, ())
        min_w, min_h = min_size
        result = []
        for snap in snapshots:
            left, top, right, bottom = snap.rect
            if left <= x < right and top <= y < bottom:
                if (right - left) >= min_w and (bottom - top) >= min_h:
                    result.append(snap)
        return tuple(result)

    def request_refresh_if_needed(self, hwnd: int):
        if hwnd in self._snapshots:
            return
        self._enqueue(hwnd, urgent=True)

    def prewarm(self, hwnds):
        for hwnd in hwnds:
            if hwnd not in self._snapshots and hwnd not in self._pending:
                self._enqueue(hwnd, urgent=False)

    def close(self):
        self._closed = True
        with self._lock:
            self._pending.clear()
        self._snapshots.clear()

    # ── 内部 ──

    def _enqueue(self, hwnd: int, *, urgent: bool):
        if self._closed:
            return
        with self._lock:
            if hwnd in self._pending:
                return
            self._pending.add(hwnd)
        worker = _MacScanWorker(hwnd, self._on_scan_done)
        worker.start()

    def _on_scan_done(self, hwnd: int, snapshots: Tuple[ElementSnapshot, ...]):
        if self._closed:
            return
        with self._lock:
            self._pending.discard(hwnd)
            if snapshots:
                self._snapshots[hwnd] = snapshots
        self.cache_updated.emit(hwnd)
        log_debug(
            T("AX 扫描完成 window={hwnd}, 控件数={count}", hwnd=hwnd, count=len(snapshots)),
            "SmartSelect",
        )


class MacOSAccessibilityBackend(AccessibilityBackend):
    """macOS 控件级元素后端（供 PlatformFactory 聚合）。"""

    def __init__(self):
        from ..base.accessibility import AccessibilityBackend as _AB  # noqa: F401
        super().__init__()
        self._finder = None

    def is_available(self) -> bool:
        return is_macos_accessibility_available()

    def scan_window(self, handle: int, max_elements: int = 4096) -> Tuple[ElementSnapshot, ...]:
        """同步扫描指定窗口（CGWindowID）下所有控件矩形，由细到粗排序。

        供平台后端 / 测试直接调用；交互路径仍走 MacAccessibilityElementFinder
        的异步扫描（不阻塞 UI）。
        """
        if not is_macos_accessibility_available():
            return ()
        pid = _pid_for_window(handle)
        if pid is None:
            return ()
        import ApplicationServices
        try:
            app = ApplicationServices.AXUIElementCreateApplication(pid)
            if app is None:
                return ()
            windows = _ax_value(app, ApplicationServices.kAXWindowsAttribute)
            out: List[ElementSnapshot] = []
            for win in windows or []:
                _scan_tree(win, out, 0, 12, max_elements)
            out.sort(key=lambda s: s.area)
            return tuple(out)
        except Exception:
            return ()

    def is_handle_hung(self, handle: int) -> bool:
        return False
