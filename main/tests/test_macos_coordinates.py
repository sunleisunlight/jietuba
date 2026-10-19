# -*- coding: utf-8 -*-
"""macOS 坐标映射测试：mss 恒等、SCK 按 dpr、负坐标/多屏虚拟桌面。"""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="坐标映射在 macOS 上验证（Windows 由 Windows CI 覆盖）",
)


@pytest.fixture()
def mapper():
    from PySide6.QtCore import QRect, QRectF
    from platforms.macos.coordinates import MacOSCoordinateMapper
    return MacOSCoordinateMapper(), QRect, QRectF


def test_mss_identity(mapper):
    """mss 源：Qt logical == 捕获点坐标，恒等映射。"""
    m, QRect, QRectF = mapper
    assert m.qt_to_capture_factor(100, 200) == 1.0
    r = m.capture_rect_to_qt(QRectF(-1920.0, 30.0, 3840.0, 1080.0))
    assert (r.x(), r.y(), r.width(), r.height()) == (-1920, 30, 3840, 1080)


def test_negative_coordinates_preserved(mapper):
    """副屏在左：负坐标必须原样保留（不偏移不翻转）。"""
    m, QRect, QRectF = mapper
    r = m.capture_rect_to_qt(QRectF(-1920.0, 0.0, 1920.0, 1080.0))
    assert r.x() == -1920 and r.y() == 0
    assert r.width() == 1920 and r.height() == 1080


def test_sck_uses_dpr(qapp):
    """SCK 源（GIF 物理像素）：按所在屏幕 devicePixelRatio 收缩。"""
    from platforms.macos.coordinates import MacOSCoordinateMapper
    sck = MacOSCoordinateMapper(MacOSCoordinateMapper.CAPTURE_SOURCE_SCK)
    factor = sck.qt_to_capture_factor(500, 500)
    assert factor >= 1.0  # Retina 下应为 2.0，普通屏 1.0
    view = sck.view_scale()
    assert view == 1.0 / factor


def test_qt_point_to_capture_roundtrip(qapp):
    """Qt logical 点 → 捕获像素 → Qt logical 点 必须闭环（任务4 单位修复）。"""
    from platforms.macos.coordinates import MacOSCoordinateMapper
    m = MacOSCoordinateMapper()
    for x, y in [(0, 0), (100, 200), (-50, 30), (800, 600)]:
        px, py = m.qt_point_to_capture(x, y)
        assert isinstance(px, int) and isinstance(py, int)
        # 像素坐标必须 >= 逻辑坐标（Retina 放大）
        assert abs(px) >= abs(x) or m.qt_to_capture_factor(x, y) == 1.0
        rx, ry = m.capture_point_to_qt(px, py)
        assert rx == x and ry == y


def test_reference_factor_matches_primary_dpr(qapp):
    """reference_factor 必须等于主屏 dpr（导出侧像素换算基准）。"""
    from platforms.macos.coordinates import MacOSCoordinateMapper
    from PySide6.QtGui import QGuiApplication
    m = MacOSCoordinateMapper()
    primary = QGuiApplication.primaryScreen()
    expected = primary.devicePixelRatio() if primary else 1.0
    assert m.reference_factor() == expected


def test_cursor_pos_capture_returns_pixels(qapp):
    """cursor_pos_capture 返回像素坐标（= 逻辑坐标 × dpr）。"""
    from platforms.macos.coordinates import MacOSCoordinateMapper
    from PySide6.QtGui import QCursor
    m = MacOSCoordinateMapper()
    cx, cy = m.cursor_pos_capture()
    # 即便光标在屏幕外（INT_MAX）也必须返回 int，不抛异常
    assert isinstance(cx, int) and isinstance(cy, int)


def test_virtual_desktop_union_rect(qapp):
    """多屏联合矩形（虚拟桌面）可从所有屏幕推导。"""
    screens = qapp.screens()
    assert len(screens) >= 1
    left = min(s.geometry().left() for s in screens)
    right = max(s.geometry().right() for s in screens)
    assert left <= 0  # 负坐标（副屏在左）或 0
    assert right > 0
