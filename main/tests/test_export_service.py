# -*- coding: utf-8 -*-
"""ExportService 导出像素对齐回归测试。

选区来自鼠标拖拽（canvas/gestures.py 用 QRectF(start_pos, scene_pos) 构造），
x/y/宽/高天然带小数。源矩形一旦不在整数格点上，Qt 就会把整张背景按非整数比例
+ 亚像素偏移重采样：预选界面是视图 1:1 直绘，看着清晰，而保存 / 复制到剪贴板 /
钉图拿到的都是这份重采样过的图，于是整体发虚。这里验证导出的像素与后台原图
对应区域逐像素完全一致。
"""
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from core.export import ExportService


def _make_source_image(width: int = 600, height: int = 400) -> QImage:
    """细密且非均匀的图案：任何亚像素重采样都会明显改动像素值。"""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        for index, x in enumerate(range(0, width, 3)):
            painter.setPen(QColor(0, 0, 0) if index % 2 else QColor(40, 90, 200))
            painter.drawLine(x, 0, x, height)
    finally:
        painter.end()
    return image


def _make_scene(image: QImage) -> QGraphicsScene:
    scene = QGraphicsScene()
    background = QGraphicsPixmapItem(QPixmap.fromImage(image))
    scene.addItem(background)
    scene.setSceneRect(QRectF(0, 0, image.width(), image.height()))
    # export_base_image_only 通过 scene.background 识别底图，这里补上同一契约
    scene.background = background
    return scene


def _rgb32(image: QImage) -> QImage:
    return image.convertToFormat(QImage.Format.Format_RGB32)


def test_fractional_selection_exports_exact_source_pixels(qapp):
    """小数选区导出后必须等于原图对应整数区域的逐像素拷贝。"""
    source = _make_source_image()
    service = ExportService(_make_scene(source))

    exported = service.export(QRectF(100.37, 100.62, 200.25, 150.11))

    assert exported.size() == QSize(200, 150)
    assert _rgb32(exported) == _rgb32(source.copy(100, 101, 200, 150))


def test_width_and_height_are_rounded_not_truncated(qapp):
    """宽高要四舍五入；截断会丢像素，还会引入非 1 的缩放比例。"""
    source = _make_source_image()
    service = ExportService(_make_scene(source))

    exported = service.export(QRectF(0.0, 0.0, 300.9, 200.9))

    assert exported.size() == QSize(301, 201)
    assert _rgb32(exported) == _rgb32(source.copy(0, 0, 301, 201))


def test_integer_selection_still_exact(qapp):
    """整数选区本来就不该有重采样，改动不能把它弄坏。"""
    source = _make_source_image()
    service = ExportService(_make_scene(source))

    exported = service.export(QRectF(50, 60, 220, 180))

    assert _rgb32(exported) == _rgb32(source.copy(50, 60, 220, 180))


def test_base_image_export_uses_same_snapping(qapp):
    """钉图 / OCR 底图走 export_base_image_only，同样不能重采样。"""
    source = _make_source_image()
    service = ExportService(_make_scene(source))

    exported = service.export_base_image_only(QRectF(50.6, 60.6, 100.6, 80.6))

    assert exported.size() == QSize(101, 81)
    assert _rgb32(exported) == _rgb32(source.copy(51, 61, 101, 81))
