# -*- coding: utf-8 -*-
"""窗口后端 — 统一窗口枚举、命中测试、前台窗口跟踪接口。

Windows 实现基于 HWND/EnumWindows/GetForegroundWindow；
macOS 实现基于 CGWindowListCopyWindowInfo / NSWorkspace。
窗口句柄类型平台相关（int），上层只做不透明标识使用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class WindowBackend(ABC):
    """平台窗口后端。"""

    @abstractmethod
    def enum_windows(self, *, offset_x: int = 0, offset_y: int = 0) -> List[Tuple[int, List[int], str]]:
        """枚举可见应用窗口，返回 [(handle, [x1,y1,x2,y2], title)]。

        坐标已减去 offset_x/offset_y（相对截图区域），与 Windows 版
        WindowFinder 的语义保持一致。
        """

    @abstractmethod
    def find_window_at_point(self, windows: List[Tuple[int, List[int], str]],
                             x: int, y: int) -> Optional[Tuple[int, List[int], str]]:
        """在给定窗口列表中做命中测试（Z 序靠前优先）。"""

    @abstractmethod
    def find_monitor_rect_at_point(self, x: int, y: int) -> List[int]:
        """鼠标所在那块屏幕的矩形（物理像素）。"""

    @abstractmethod
    def get_foreground_handle(self) -> Optional[int]:
        """当前前台窗口句柄；取不到返回 None。"""

    @abstractmethod
    def foreground_pid(self, handle: Optional[int]) -> Optional[int]:
        """窗口/前台应用所属 PID。"""

    @abstractmethod
    def is_alive(self, handle: Optional[int]) -> bool:
        """句柄是否仍指向一个存在且可见的窗口。"""

    @abstractmethod
    def can_take_focus(self, handle: Optional[int]) -> bool:
        """窗口能否接受键盘焦点。"""

    @abstractmethod
    def set_foreground(self, handle: Optional[int]) -> bool:
        """把目标窗口切到前台。"""

    @abstractmethod
    def set_window_click_through(self, widget, enable: bool) -> None:
        """设置窗口鼠标穿透（GIF overlay / 长截图预览用）。"""

    @abstractmethod
    def set_window_topmost(self, widget, enable: bool) -> None:
        """设置窗口置顶（钉图压制/恢复用）。"""

    @abstractmethod
    def set_window_exclude_from_capture(self, widget, exclude: bool) -> None:
        """设置窗口对屏幕截图 API 不可见（截图浮层自排除）。"""
