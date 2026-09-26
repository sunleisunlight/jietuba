# -*- coding: utf-8 -*-
"""Windows 无障碍后端 — 适配现有 UIAElementFinder（comtypes/UIAutomationCore）。"""
from __future__ import annotations

from typing import Tuple

from ..base.accessibility import AccessibilityBackend, ElementSnapshot


class WindowsAccessibilityBackend(AccessibilityBackend):
    """Windows 控件级智能选区：UI Automation。"""

    def is_available(self) -> bool:
        try:
            from capture.uia_element_finder import is_uia_available
            return is_uia_available()
        except Exception:
            return False

    def scan_window(self, handle: int, max_elements: int = 4096) -> Tuple[ElementSnapshot, ...]:
        """同步扫描接口，仅供工作线程调用；UI 继续使用原有异步 finder。

        COM 后端必须在同一线程创建、扫描和释放。不能把接口接线错误吞成空选区。
        """
        from capture.uia_element_finder import _UIABackend, is_uia_available

        if not is_uia_available() or max_elements <= 0:
            return ()
        backend = _UIABackend()
        try:
            snapshots = backend.scan(handle)[:max_elements]
            return tuple(sorted(
                (ElementSnapshot(s.rect, s.order) for s in snapshots),
                key=lambda s: (s.area, -s.order),
            ))
        finally:
            backend.close()

    def is_handle_hung(self, handle: int) -> bool:
        from capture.uia_element_finder import is_hung_window
        return is_hung_window(handle)
