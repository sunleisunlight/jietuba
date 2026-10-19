# -*- coding: utf-8 -*-
"""macOS 屏幕捕获后端 — CoreGraphics（CGWindowListCreateImage）物理像素。

为什么不用 mss：mss 在 macOS 上用 point 尺寸的 CGRect 抓图，Retina 上只拿到
逻辑点分辨率（如 1920x1080），屏幕物理像素是其 2 倍，导致截图模糊。
``CGWindowListCreateImage(CGRectInfinite)`` 返回覆盖整个虚拟桌面的物理像素
图像（如双 4K 为 7680x2160），与 Windows 的全分辨率截图对齐。

权限未授予时抛出 ScreenCapturePermissionError，由 UI 层翻译成
"需要屏幕录制权限"引导提示（而不是让用户看到黑屏/空截图）。
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtGui import QImage
from PySide6.QtCore import QRectF

from ..base.capture import CaptureBackend
from .permissions import _cg_preflight
from .coordinates import MacOSCoordinateMapper


class ScreenCapturePermissionError(RuntimeError):
    """屏幕录制权限未授予。"""

    def __init__(self):
        super().__init__("macOS 屏幕录制权限未授予")


def _cg_image_to_qimage(cg_image) -> QImage:
    """把 CGImage（32bpp 小端 BGRA）转成 QImage（Format_RGB32），并持有字节。"""
    import Quartz

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

    provider = Quartz.CGImageGetDataProvider(cg_image)
    cf_data = Quartz.CGDataProviderCopyData(provider)
    # 拷贝出独立字节，避免依赖 CFData/CGImage 的生命周期
    raw = bytes(cf_data)

    qimage = QImage(raw, width, height, bytes_per_row, QImage.Format.Format_RGB32)
    return qimage.copy()


class MacOSCaptureBackend(CaptureBackend):
    """macOS 截图后端（CoreGraphics 物理像素）。"""

    def __init__(self):
        self._mapper = MacOSCoordinateMapper()

    def is_available(self) -> bool:
        return _cg_preflight()

    def capture_all_screens(self) -> Tuple[QImage, QRectF]:
        if not _cg_preflight():
            raise ScreenCapturePermissionError()

        import Quartz

        cg_image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectInfinite,
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID,
            Quartz.kCGWindowImageDefault,
        )
        if cg_image is None:
            # 拿不到图像通常意味着权限被拒（返回空桌面而非黑屏）
            raise ScreenCapturePermissionError()

        image = _cg_image_to_qimage(cg_image)

        # 物理像素 bbox：图像像素 (0,0) 对应 point bbox 左上。
        point_bbox = self._mapper.virtual_point_bbox()
        factor_tl = self._mapper.qt_to_capture_factor(
            int(point_bbox.left()), int(point_bbox.top()))
        rect = QRectF(
            point_bbox.left() * factor_tl,
            point_bbox.top() * factor_tl,
            image.width(),
            image.height(),
        )
        return image, rect

    # ── 窗口/单屏捕获（任务2基础窗口捕获）──

    def capture_window(self, window_id: int, *, include_shadow: bool = True) -> Optional[QImage]:
        """抓取单个 CGWindowID 窗口（含阴影可选），物理像素。"""
        if not _cg_preflight():
            raise ScreenCapturePermissionError()

        import Quartz

        image_option = Quartz.kCGWindowImageDefault
        if not include_shadow:
            image_option = Quartz.kCGWindowImageBoundsIgnoreFraming

        cg_image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectInfinite,
            Quartz.kCGWindowListOptionIncludingWindow,
            int(window_id),
            image_option,
        )
        if cg_image is None:
            return None
        return _cg_image_to_qimage(cg_image)
