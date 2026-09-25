# -*- coding: utf-8 -*-
"""坐标映射 — 统一 Qt logical point ↔ 屏幕物理像素 ↔ 截图像素。

问题背景：
  - Windows（QT_ENABLE_HIGHDPI_SCALING=0）：Qt 坐标即物理像素，
    与 mss/BitBlt 的像素一致，映射为恒等。
  - macOS Retina：Qt 使用逻辑 point（如 1512x982），mss/CG 返回物理像素
    （如 3024x1964）。鼠标框选 A 区域却截到 B 区域、尺寸翻倍都源于
    这里忘了换算。
所有模块的 *2 / /2 一律收敛到本类，禁止在各处手写。
"""
from __future__ import annotations

from abc import ABC
from typing import Tuple

from PySide6.QtCore import QPoint, QRect, QRectF
from PySide6.QtGui import QGuiApplication, QCursor


class CoordinateMapper(ABC):
    """坐标映射器（平台差异集中在实现类）。"""

    # ── 比例 ──────────────────────────────────────────────

    def qt_to_capture_factor(self, x: int = 0, y: int = 0) -> float:
        """Qt logical point → 截图物理像素的换算系数。Windows=1.0。"""
        return 1.0

    # ── 点 ────────────────────────────────────────────────

    def qt_point_to_capture(self, x: int, y: int) -> Tuple[int, int]:
        """Qt logical 坐标 → 截图物理像素坐标。"""
        factor = self.qt_to_capture_factor(x, y)
        return int(round(x * factor)), int(round(y * factor))

    def capture_point_to_qt(self, x: int, y: int) -> Tuple[int, int]:
        """截图物理像素坐标 → Qt logical 坐标。"""
        factor = self.qt_to_capture_factor(x, y)
        if factor == 1.0:
            return int(x), int(y)
        return int(round(x / factor)), int(round(y / factor))

    def cursor_pos_capture(self) -> Tuple[int, int]:
        """当前鼠标位置（截图物理像素坐标系）。"""
        pos = QCursor.pos()
        return self.qt_point_to_capture(pos.x(), pos.y())

    # ── 矩形 ──────────────────────────────────────────────

    def capture_rect_to_qt(self, rect: QRectF) -> QRect:
        """截图物理像素矩形 → Qt logical 窗口几何。

        macOS Retina 下把 2x 像素窗口缩小到逻辑点尺寸，配合
        CanvasView 的 1/dpr 缩放，实现「场景=像素、屏幕=点」。
        """
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
        """QGraphicsView 场景→视口的缩放系数。Windows=1.0，Retina=1/dpr。"""
        return 1.0

    # ── 屏幕 ──────────────────────────────────────────────

    @staticmethod
    def _screen_at(logical_x: int, logical_y: int):
        """返回包含该逻辑点的 QScreen（找不到返回主屏）。"""
        try:
            for screen in QGuiApplication.screens():
                if screen.geometry().contains(logical_x, logical_y):
                    return screen
        except Exception:
            pass
        return QGuiApplication.primaryScreen()
