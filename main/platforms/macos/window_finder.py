# -*- coding: utf-8 -*-
"""macOS 智能窗口选择器 — CGWindowListCopyWindowInfo 实现。

与 Windows WindowFinder 保持同一上层接口：
  - find_windows()            枚举可见窗口（Z 序从顶到底）
  - find_window_at_point_info() 命中测试（返回句柄+矩形+标题）
  - windows_by_exposed_area()  按露出面积排序的句柄
  - find_monitor_rect_at_point() 鼠标所在屏幕矩形
句柄使用 CGWindowID（kCGWindowNumber），坐标使用 CG 全局显示坐标
（物理像素，与 mss 截图一致）。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion

from core.logger import T, log_debug, log_error

from .window import MacOSWindowBackend


class MacWindowFinder:
    """macOS 智能窗口选择器（接口对齐 Windows WindowFinder）。"""

    def __init__(self, screen_offset_x: int = 0, screen_offset_y: int = 0):
        self.windows: List[Tuple[int, List[int], str]] = []
        self.screen_offset_x = screen_offset_x
        self.screen_offset_y = screen_offset_y
        self.debug = False
        self._backend = MacOSWindowBackend()

    def set_screen_offset(self, offset_x: int, offset_y: int):
        self.screen_offset_x = offset_x
        self.screen_offset_y = offset_y

    def find_windows(self):
        """枚举所有可见应用窗口（CGWindowListCopyWindowInfo）。"""
        try:
            self.windows = self._backend.enum_windows(
                offset_x=self.screen_offset_x, offset_y=self.screen_offset_y
            )
            if self.debug:
                log_debug(T("找到 {count} 个有效窗口", count=len(self.windows)), module="SmartSelection")
        except Exception as e:
            log_error(T("枚举窗口失败: {e}", e=e), module="SmartSelection")
            self.windows = []

    def windows_by_exposed_area(self) -> List[int]:
        """按露在外面的面积从大到小排的窗口句柄，完全被遮住的不返回。"""
        covered = QRegion()
        scored = []
        for hwnd, rect, _title in self.windows:
            shape = QRegion(QRect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]))
            exposed = shape.subtracted(covered)
            area = sum(part.width() * part.height() for part in exposed)
            if area > 0:
                scored.append((area, hwnd))
            covered = covered.united(shape)
        scored.sort(key=lambda item: -item[0])
        return [hwnd for _area, hwnd in scored]

    def find_window_at_point_info(self, x: int, y: int) -> Optional[Tuple[int, List[int], str]]:
        """返回鼠标下方已缓存窗口的句柄、矩形和标题。"""
        for hwnd, rect, title in self.windows:
            x1, y1, x2, y2 = rect
            if x1 <= x <= x2 and y1 <= y <= y2:
                return hwnd, rect, title
        return None

    def find_window_at_point(self, x: int, y: int, fallback_rect: Optional[List[int]] = None) -> List[int]:
        """根据鼠标位置查找最顶层的包含窗口（CGWindowList 已按 Z 序排列）。"""
        for idx, (hwnd, rect, title) in enumerate(self.windows):
            x1, y1, x2, y2 = rect
            if x1 <= x <= x2 and y1 <= y <= y2:
                if self.debug:
                    log_debug(
                        T("鼠标({x}, {y})处找到窗口: '{title}', 大小: {width}x{height}, Z-order: {idx}",
                          x=x, y=y, title=title[:30], width=x2 - x1, height=y2 - y1, idx=idx),
                        module="SmartSelection",
                    )
                return rect
        if fallback_rect:
            return fallback_rect
        return self._get_virtual_desktop_rect()

    def find_monitor_rect_at_point(self, x: int, y: int) -> List[int]:
        """鼠标所在那块屏幕的矩形（物理像素）。"""
        try:
            rect = self._backend.find_monitor_rect_at_point(x, y)
            if rect[2] > rect[0] and rect[3] > rect[1]:
                return rect
        except Exception:
            pass
        return self._get_virtual_desktop_rect()

    def _get_virtual_desktop_rect(self) -> List[int]:
        """虚拟桌面矩形（CGDisplay 联合边界）。"""
        try:
            import Quartz
            bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            return [
                int(bounds.origin.x), int(bounds.origin.y),
                int(bounds.origin.x + bounds.size.width),
                int(bounds.origin.y + bounds.size.height),
            ]
        except Exception:
            return [0, 0, 1920, 1080]

    def clear(self):
        self.windows = []


def is_smart_selection_available() -> bool:
    """macOS 窗口检测不依赖辅助功能权限，CGWindowList 始终可用。"""
    return True
