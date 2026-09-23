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
        try:
            from capture.uia_element_finder import (
                get_snapshot_generator,
                is_uia_available,
            )
            if not is_uia_available():
                return ()
            generator = get_snapshot_generator()
            snapshots = generator(handle, max_elements=max_elements)
            return tuple(ElementSnapshot(s.rect, s.order) for s in snapshots)
        except Exception:
            return ()

    def is_handle_hung(self, handle: int) -> bool:
        try:
            from capture.uia_element_finder import is_hwnd_hung
            return is_hwnd_hung(handle)
        except Exception:
            return False
