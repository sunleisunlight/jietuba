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


class ScreenCaptureError(RuntimeError):
    """抓屏本身失败，但不是权限问题。

    ``CGWindowListCreateImage`` 在系统内存紧张 / 窗口服务器繁忙时会返回空图；
    这跟"没授权"是两回事，不能再把用户拉去系统设置里反复授权。
    """


class _OwnedQImage(QImage):
    """QImage 视图 + 持有底层 Python bytes，避免再做一次全屏 copy。

    QImage(raw, ...) 在 PySide6 中是零拷贝视图；如果只返回 QImage，raw 离开
    作用域后底层缓冲就会失效。把 raw 挂在这个子类实例上，生命周期跟着截图
    会话走即可。背景图只读，不会触发 Qt 的写时复制。
    """

    def __init__(self, raw: bytes, width: int, height: int, bytes_per_row: int):
        super().__init__(raw, width, height, bytes_per_row, QImage.Format.Format_RGB32)
        self._raw = raw


def _cg_image_to_qimage(cg_image) -> QImage:
    """把 CGImage（32bpp 小端 BGRA）转成 QImage（Format_RGB32）。

    只做一次 bytes 拷贝，并让 QImage 直接引用这块内存；不再调用
    ``QImage.copy()``。Retina/多屏全屏图单份约 24–78MB，少一份拷贝就是
    实打实的内存峰值下降。
    """
    import Quartz

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

    provider = Quartz.CGImageGetDataProvider(cg_image)
    cf_data = Quartz.CGDataProviderCopyData(provider)
    # 拷贝出独立字节，避免依赖 CFData/CGImage 的生命周期。
    #
    # 必须用 memoryview().tobytes()，不能用 bytes(cf_data)：PyObjC 的
    # bytes(CFData) 会额外长期保留一份底层缓冲，实测每抓一次屏就漏掉一整张
    # 全屏位图（2880×1800 约 20MB）。连截十几次后内存翻倍，macOS 开始压缩
    # 换页，于是「截完一张就卡、再截就截不动」。
    raw = memoryview(cf_data).tobytes()
    if not raw:
        return QImage()

    return _OwnedQImage(raw, width, height, bytes_per_row)


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
            # 预检已通过却拿到空图：不是权限问题，别再把用户拉去授权。
            if _cg_preflight():
                raise ScreenCaptureError("系统暂时无法完成屏幕采集，请稍后重试")
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
