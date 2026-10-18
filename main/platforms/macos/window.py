# -*- coding: utf-8 -*-
"""macOS 窗口后端 — CGWindowListCopyWindowInfo + NSWorkspace + Qt 窗口属性。

窗口句柄约定：macOS 没有 HWND 概念，使用 CGWindowID（kCGWindowNumber）
作为不透明标识；前台窗口跟踪按"应用"粒度（PID）进行，因为 macOS 的
激活/键盘焦点是应用级的。
"""
from __future__ import annotations

import os
import logging
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt

from ..base.window import WindowBackend

# 排除的"壳"窗口：桌面、菜单栏、Dock 之外的系统层
_SHELL_OWNERS = frozenset({"Window Server", "Dock"})
_SHELL_LAYERS = {0, 25}  # 常规窗口层 0；菜单栏 24 / 桌面 1 由 layer 过滤
_MIN_WINDOW_SIZE = 30
_MAX_WINDOW_SIZE = 20000
_log = logging.getLogger(__name__)


def _native_window(widget):
    """Qt Cocoa 的 winId 是 NSView 指针，而非 NSWindow。"""
    import objc
    view = objc.objc_object(c_void_p=int(widget.winId()))
    return view.window()


def _window_list(on_screen_only: bool = True) -> list:
    """获取 CGWindowListCopyWindowInfo 原始列表（PyObjC Quartz）。"""
    import Quartz

    option = Quartz.kCGWindowListOptionOnScreenOnly if on_screen_only else (
        Quartz.kCGWindowListOptionAll
    )
    info_list = Quartz.CGWindowListCopyWindowInfo(option, Quartz.kCGNullWindowID)
    return info_list or []


class MacOSWindowBackend(WindowBackend):
    """macOS 窗口后端。"""

    # ── 窗口枚举（WindowFinder 兼容接口）──

    def enum_windows(self, *, offset_x: int = 0, offset_y: int = 0) -> List[Tuple[int, List[int], str]]:
        results: List[Tuple[int, List[int], str]] = []
        try:
            windows = _window_list()
            # CGWindowList 返回顺序即 Z 序（数组头部在上方）
            for win in windows:
                try:
                    layer = win.get("kCGWindowLayer", 0)
                    if layer != 0:
                        continue
                    owner = win.get("kCGWindowOwnerName", "") or ""
                    if owner in _SHELL_OWNERS:
                        continue
                    name = win.get("kCGWindowName", "") or ""
                    if not name and not owner:
                        continue
                    if win.get("kCGWindowIsOnscreen", False) is False:
                        continue
                    bounds = win.get("kCGWindowBounds", None)
                    if not bounds:
                        continue
                    left = int(bounds.get("X", 0))
                    top = int(bounds.get("Y", 0))
                    width = int(bounds.get("Width", 0))
                    height = int(bounds.get("Height", 0))
                    if width < _MIN_WINDOW_SIZE or height < _MIN_WINDOW_SIZE:
                        continue
                    if width > _MAX_WINDOW_SIZE or height > _MAX_WINDOW_SIZE:
                        continue
                    # alpha 低于 0.3 的窗口视为不可见
                    alpha = win.get("kCGWindowAlpha", 1.0)
                    if alpha is not None and alpha < 0.3:
                        continue
                    number = win.get("kCGWindowNumber", 0)
                    results.append((
                        int(number),
                        [left - offset_x, top - offset_y,
                         left + width - offset_x, top + height - offset_y],
                        name,
                    ))
                except Exception:
                    continue
        except Exception:
            pass
        return results

    def find_window_at_point(self, windows, x: int, y: int):
        # 列表按 Z 序排列（头部最上层），返回第一个命中的
        for handle, rect, title in windows:
            left, top, right, bottom = rect
            if left <= x < right and top <= y < bottom:
                return handle, rect, title
        return None

    def find_monitor_rect_at_point(self, x: int, y: int) -> List[int]:
        try:
            import Quartz
            error, displays, count = Quartz.CGGetActiveDisplayList(32, None, None)
            if error != Quartz.kCGErrorSuccess:
                raise RuntimeError(f"CGGetActiveDisplayList: {error}")
            for display in displays[:count]:
                bounds = Quartz.CGDisplayBounds(display)
                left = int(bounds.origin.x)
                top = int(bounds.origin.y)
                w = int(bounds.size.width)
                h = int(bounds.size.height)
                if left <= x < left + w and top <= y < top + h:
                    return [left, top, left + w, top + h]
        except Exception:
            _log.exception("查询显示器边界失败")
        return [0, 0, 0, 0]

    # ── 前台跟踪（按应用 PID 粒度）──

    def get_foreground_handle(self) -> Optional[int]:
        """返回前台应用 PID（macOS 激活粒度为应用）。"""
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is not None:
                pid = app.processIdentifier()
                return int(pid)
            return None
        except Exception:
            return None

    def is_alive(self, handle: Optional[int]) -> bool:
        if not handle:
            return False
        try:
            return os.kill(handle, 0) is None
        except PermissionError:
            return True
        except OSError:
            return False

    def foreground_pid(self, handle: Optional[int]) -> Optional[int]:
        # macOS 前台句柄即 PID
        return int(handle) if handle else None

    def window_class(self, handle: int) -> str:
        """窗口"类名"→ 返回前台应用 bundle id（粘贴排除判断用）。"""
        try:
            from AppKit import NSRunningApplication
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(handle)
            if app is not None:
                return app.bundleIdentifier() or ""
            return ""
        except Exception:
            return ""

    def can_take_focus(self, handle: Optional[int]) -> bool:
        if not handle:
            return False
        try:
            from AppKit import NSRunningApplication
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(handle)
            if app is None:
                return False
            policy = app.activationPolicy()
            # 0=NSApplicationActivationPolicyRegular（可聚焦），2=Accessory/Prohibited
            return policy == 0
        except Exception:
            return True

    def is_shell_window(self, handle: int) -> bool:
        """前台应用是否属于"壳"（Dock/WindowServer）。"""
        try:
            from AppKit import NSRunningApplication
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(handle)
            if app is None:
                return True
            bid = app.bundleIdentifier() or ""
            return bid in ("com.apple.dock", "com.apple.WindowServer")
        except Exception:
            return False

    def current_pid(self) -> int:
        return os.getpid()

    # ── 激活 ──

    def set_foreground(self, handle: Optional[int]) -> bool:
        """激活目标应用（NSRunningApplication.activate）。"""
        if not handle:
            return False
        try:
            from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(handle)
            if app is None:
                return False
            return bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
        except Exception:
            return False

    # ── Qt 窗口属性（macOS 用 Qt 原生能力）──

    def set_window_click_through(self, widget, enable: bool) -> None:
        try:
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enable)
            window = _native_window(widget)
            if window is not None:
                window.setIgnoresMouseEvents_(bool(enable))
        except Exception:
            _log.exception("设置 macOS 原生窗口鼠标穿透失败")

    def set_window_topmost(self, widget, enable: bool) -> None:
        try:
            flags = widget.windowFlags()
            if enable:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            widget.setWindowFlags(flags)
            widget.show()
        except Exception:
            pass

    def set_window_exclude_from_capture(self, widget, exclude: bool) -> None:
        """静态截图在浮层显示前捕获；录屏的 SCK filter 排除本应用窗口。

        此处不是系统级隐私保护，无法保证其它录屏软件不捕获本窗口。
        """
        from core.logger import log_debug
        log_debug("macOS: 本应用录屏通过 ScreenCaptureKit 排除自身窗口", "Platform")
