# -*- coding: utf-8 -*-
"""macOS 坐标映射：逻辑点（point）↔ 物理像素（physical pixel）。

坐标约定（重要，已用标记实验核实）：
  - 屏幕/窗口/鼠标坐标与 setGeometry 单位都是 **point**（Qt Cocoa 恒用 point，
    ``QT_ENABLE_HIGHDPI_SCALING=0`` 在 cocoa 上不改变这点）。
  - 静态截图改用 ``CGWindowListCreateImage`` 后返回 **物理像素**：
    point ``(px, py)`` → 图像像素 ``((px-bbox.left)*dpr, (py-bbox.top)*dpr)``，
    其中 dpr 为该点所在屏幕的 devicePixelRatio（Retina 上 2.0）。
  - 因此场景与 Windows 一样按物理像素组织，CanvasView 再整体缩放 1/dpr，
    实现「场景=像素、屏幕=点」。线宽/字号/选区与 Windows 完全一致。

混合缩放（不同屏幕 dpr 不同）：QGraphicsView 只有一个 transform，
``CGWindowListCreateImage`` 也以主屏（reference display）为统一像素网格，
故这里 view_scale / 全局因子取主屏 dpr；同 dpr 多屏精确，混合 dpr 需
实机验证，无设备时记为环境阻塞。

所有换算集中在本模块，避免各业务层自行 *2 / /2。
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QGuiApplication

from ..base.coordinates import CoordinateMapper


class MacOSCoordinateMapper(CoordinateMapper):
    """macOS 坐标映射（point ↔ 物理像素）。"""

    #: 静态截图源：CGWindowListCreateImage，物理像素
    CAPTURE_SOURCE_CG = "cg"
    #: ScreenCaptureKit 源（GIF 录制，任务4）：物理像素
    CAPTURE_SOURCE_SCK = "sck"

    def __init__(self, capture_source: str = CAPTURE_SOURCE_CG):
        super().__init__()
        self._capture_source = capture_source

    # ── 比例 ──────────────────────────────────────────────

    def qt_to_capture_factor(self, x: int = 0, y: int = 0) -> float:
        """point → 物理像素：该点所在屏幕的 devicePixelRatio。"""
        screen = self._screen_at(int(x), int(y))
        if screen is None:
            return 1.0
        return float(screen.devicePixelRatio())

    def reference_factor(self) -> float:
        """主屏（reference display）的 dpr，全局像素网格的统一比例。"""
        primary = QGuiApplication.primaryScreen()
        if primary is None:
            return 1.0
        return float(primary.devicePixelRatio())

    # ── 矩形 ──────────────────────────────────────────────

    def capture_rect_to_qt(self, rect: QRectF) -> QRect:
        """物理像素矩形 → point 窗口几何（按左上所在屏 dpr 收缩）。

        同 dpr 多屏精确；混合 dpr 时以左上屏 dpr 为该矩形的比例。
        """
        factor = self.qt_to_capture_factor(int(rect.x()), int(rect.y()))
        if factor == 1.0:
            return QRect(int(round(rect.x())), int(round(rect.y())),
                         int(round(rect.width())), int(round(rect.height())))
        return QRect(
            int(round(rect.x() / factor)),
            int(round(rect.y() / factor)),
            int(round(rect.width() / factor)),
            int(round(rect.height() / factor)),
        )

    def view_scale(self) -> float:
        """场景（物理像素）→ 视口（point）的缩放：1/主屏 dpr。"""
        factor = self.reference_factor()
        return 1.0 if factor == 1.0 else 1.0 / factor

    # ── 虚拟桌面几何 ──────────────────────────────────────

    @staticmethod
    def virtual_point_bbox() -> QRectF:
        """所有屏幕并集的 point bbox（Qt virtualGeometry）。"""
        vscreens = QGuiApplication.screens()
        if not vscreens:
            return QRectF()
        bbox = QRectF(vscreens[0].virtualGeometry())
        for screen in vscreens[1:]:
            bbox = bbox.united(QRectF(screen.virtualGeometry()))
        return bbox
