# -*- coding: utf-8 -*-
"""macOS 坐标映射。

坐标来源约定（重要）：
  - mss 在 macOS 上用 CGDisplayBounds 取显示器边界，返回的是 **point**（如
    4K@200% 显示为 1920x1080），与 Qt logical point 同一坐标系，两者 1:1，
    不需要缩放。因此静态截图路径（mss）的 factor 恒为 1.0。
  - ScreenCaptureKit（GIF 录制，阶段4）返回的是**物理像素**（3840x2160），
    届时通过 physical_capture_factor 显式换算，不要混用。
所有换算集中在本模块，避免各业务层自行 *2 / /2。
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF

from ..base.coordinates import CoordinateMapper


class MacOSCoordinateMapper(CoordinateMapper):
    """macOS 坐标映射（mss 点坐标 == Qt logical，恒等；物理像素另走显式换算）。"""

    #: mss 静态截图源：点坐标，与 Qt logical 一致
    CAPTURE_SOURCE_MSS = "mss"
    #: ScreenCaptureKit 截图源：物理像素
    CAPTURE_SOURCE_SCK = "sck"

    def __init__(self, capture_source: str = CAPTURE_SOURCE_MSS):
        super().__init__()
        self._capture_source = capture_source

    def qt_to_capture_factor(self, x: int = 0, y: int = 0) -> float:
        """Qt logical → 当前截图源的缩放系数。

        mss 源恒为 1.0（点坐标即逻辑坐标）；SCK 源为该点所在屏幕的
        devicePixelRatio（物理像素 = 逻辑点 × dpr）。
        """
        if self._capture_source != self.CAPTURE_SOURCE_SCK:
            return 1.0
        screen = self._screen_at(int(x), int(y))
        if screen is None:
            return 1.0
        return float(screen.devicePixelRatio())

    def capture_rect_to_qt(self, rect: QRectF) -> QRect:
        """截图源坐标 → Qt 窗口几何。mss 源恒等，SCK 源按 dpr 收缩。"""
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
        """QGraphicsView 场景→视口缩放。mss 源 1.0；SCK 源 1/dpr。"""
        if self._capture_source != self.CAPTURE_SOURCE_SCK:
            return 1.0
        screen = self._screen_at(0, 0)
        if screen is None:
            return 1.0
        return 1.0 / float(screen.devicePixelRatio())
