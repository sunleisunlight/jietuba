# -*- coding: utf-8 -*-
"""无障碍/控件级智能选区后端 — 统一控件矩形扫描接口。

Windows 实现走 UI Automation（comtypes/UIAutomationCore.dll）；
macOS 实现走 Accessibility (AXUIElement)。
两者都只上报平台无关的 ElementSnapshot（rect/order/contains）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple


class ElementSnapshot:
    """平台无关的控件矩形快照（与 Windows UIAElementSnapshot 同构）。"""

    __slots__ = ("rect", "order")

    def __init__(self, rect: Tuple[int, int, int, int], order: int = 0):
        self.rect = rect
        self.order = order

    @property
    def area(self) -> int:
        left, top, right, bottom = self.rect
        return (right - left) * (bottom - top)

    def contains(self, x: int, y: int) -> bool:
        left, top, right, bottom = self.rect
        return left <= x < right and top <= y < bottom

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"ElementSnapshot(rect={self.rect}, order={self.order})"


class AccessibilityBackend(ABC):
    """平台控件级元素后端。"""

    @abstractmethod
    def is_available(self) -> bool:
        """控件级能力是否可用（权限已授予且依赖齐全）。"""

    @abstractmethod
    def scan_window(self, handle: int, max_elements: int = 4096) -> Tuple[ElementSnapshot, ...]:
        """扫描指定窗口（by handle）下所有控件矩形，由细到粗排序。"""

    def is_handle_hung(self, handle: int) -> bool:
        """目标窗口是否已无响应（无响应时跳过预扫描）。默认 False。"""
        return False
