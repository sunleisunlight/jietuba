# -*- coding: utf-8 -*-
"""macOS 坐标映射 — Retina 物理像素 ↔ Qt logical point。

Qt 在 macOS 始终使用 logical point（如 1512x982），而 mss / CGWindow /
CGDisplay 返回物理像素（如 3024x1964）。所有换算集中在此：
  - qt→capture: 乘该点所在屏幕的 devicePixelRatio
  - capture→qt: 除 dpr
  - capture_rect_to_qt: 窗口几何从像素缩到点
  - view_scale: QGraphicsView 场景→视口缩放 = 1/dpr
多屏各屏 dpr 可能不同，按逻辑点所在屏幕取 dpr。
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF

from ..base.coordinates import CoordinateMapper


class MacOSCoordinateMapper(CoordinateMapper):
    """macOS Retina 坐标映射。"""

    def qt_to_capture_factor(self, x: int = 0, y: int = 0) -> float:
        screen = self._screen_at(int(x), int(y))
        if screen is None:
            return 1.0
        return float(screen.devicePixelRatio())

    def capture_rect_to_qt(self, rect: QRectF) -> QRect:
        factor = self.qt_to_capture_factor(int(rect.x()), int(rect.y()))
        if factor == 1.0:
            return QRect(int(rect.x()), int(rect.y()),
                         int(rect.width()), int(rect.height()))
        return QRect(
            int(round(rect.x() / factor)),
            int(round(rect.y() / factor)),
            int(round(rect.width() / factor)),
            int(round(rect.height() / factor)),
        )

    def view_scale(self) -> float:
        screen = self._screen_at(0, 0)
        if screen is None:
            return 1.0
        return 1.0 / float(screen.devicePixelRatio())
