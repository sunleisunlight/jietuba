# -*- coding: utf-8 -*-
"""Windows 窗口后端 — Win32 原生实现（从各模块平移，逻辑不变）。

覆盖：前台窗口跟踪、激活、鼠标穿透、置顶、截图自排除。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import List, Optional, Tuple

from ..base.window import WindowBackend

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
_user32.SetWindowLongW.restype = wintypes.LONG
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.restype = wintypes.BOOL
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

SW_RESTORE = 9
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# 任务栏、通知区域溢出面板、桌面。粘进这些窗口没有意义。
_SHELL_CLASSES = frozenset({
    "Shell_TrayWnd",
    "NotifyIconOverflowWindow",
    "TrayNotifyWnd",
    "Progman",
    "WorkerW",
})


class WindowsWindowBackend(WindowBackend):
    """Windows 窗口后端。"""

    # ── 前台跟踪 ──

    def get_foreground_handle(self) -> Optional[int]:
        try:
            return _user32.GetForegroundWindow() or None
        except Exception:
            return None

    def is_alive(self, handle: Optional[int]) -> bool:
        if not handle:
            return False
        try:
            return bool(_user32.IsWindow(handle)) and bool(_user32.IsWindowVisible(handle))
        except Exception:
            return False

    def foreground_pid(self, handle: Optional[int]) -> Optional[int]:
        try:
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            return pid.value or None
        except Exception:
            return None

    def window_class(self, handle: int) -> str:
        try:
            buffer = ctypes.create_unicode_buffer(256)
            if _user32.GetClassNameW(handle, buffer, len(buffer)) <= 0:
                return ""
            return buffer.value
        except Exception:
            return ""

    def can_take_focus(self, handle: Optional[int]) -> bool:
        if not handle:
            return False
        try:
            return not (_user32.GetWindowLongW(handle, GWL_EXSTYLE) & WS_EX_NOACTIVATE)
        except Exception:
            return True

    def is_shell_window(self, handle: int) -> bool:
        return self.window_class(handle) in _SHELL_CLASSES

    def current_pid(self) -> int:
        return _kernel32.GetCurrentProcessId()

    # ── 激活 ──

    def set_foreground(self, handle: Optional[int]) -> bool:
        if not handle:
            return False
        current_thread = None
        target_thread = None
        attached = False
        try:
            if _user32.IsIconic(handle):
                _user32.ShowWindow(handle, SW_RESTORE)
            current_thread = _kernel32.GetCurrentThreadId()
            target_thread = _user32.GetWindowThreadProcessId(handle, None)
            if target_thread and target_thread != current_thread:
                attached = bool(_user32.AttachThreadInput(current_thread, target_thread, True))
            _user32.BringWindowToTop(handle)
            return bool(_user32.SetForegroundWindow(handle))
        except Exception:
            return False
        finally:
            if attached:
                _user32.AttachThreadInput(current_thread, target_thread, False)

    # ── 窗口属性 ──

    def set_window_click_through(self, widget, enable: bool) -> None:
        try:
            hwnd = int(widget.winId())
            ex_style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enable:
                ex_style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                ex_style &= ~(WS_EX_TRANSPARENT | WS_EX_LAYERED)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        except Exception:
            pass

    def set_window_topmost(self, widget, enable: bool) -> None:
        try:
            hwnd = int(widget.winId())
            flag = HWND_TOPMOST if enable else HWND_NOTOPMOST
            _user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            pass

    def set_window_exclude_from_capture(self, widget, exclude: bool) -> None:
        try:
            hwnd = int(widget.winId())
            _user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE)
        except Exception:
            pass

    # ── 窗口枚举（WindowFinder 兼容接口）──

    def enum_windows(self, *, offset_x: int = 0, offset_y: int = 0) -> List[Tuple[int, List[int], str]]:
        """枚举可见顶层窗口（与 WindowFinder 同语义）。"""
        results: List[Tuple[int, List[int], str]] = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            rect = wintypes.RECT()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            results.append((
                int(hwnd),
                [rect.left - offset_x, rect.top - offset_y, rect.right - offset_x, rect.bottom - offset_y],
                buffer.value,
            ))
            return True

        try:
            _user32.EnumWindows(EnumWindowsProc(_cb), 0)
        except Exception:
            pass
        return results

    def find_window_at_point(self, windows, x: int, y: int):
        for hwnd, rect, title in windows:
            left, top, right, bottom = rect
            if left <= x < right and top <= y < bottom:
                return hwnd, rect, title
        return None

    def find_monitor_rect_at_point(self, x: int, y: int) -> List[int]:
        try:
            MONITOR_DEFAULTTONEAREST = 2
            monitor = _user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
            if monitor:
                info = wintypes.MONITORINFO()
                info.cbSize = ctypes.sizeof(wintypes.MONITORINFO)
                if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    r = info.rcMonitor
                    return [r.left, r.top, r.right, r.bottom]
        except Exception:
            pass
        return [0, 0, 0, 0]
