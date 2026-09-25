# -*- coding: utf-8 -*-
"""macOS 屏幕捕获后端 — mss + 屏幕录制权限检查。

权限未授予时抛出 ScreenCapturePermissionError，由 UI 层翻译成
"需要屏幕录制权限"引导提示（而不是让用户看到黑屏/空截图）。
"""
from __future__ import annotations

from typing import Tuple

import mss
from PySide6.QtGui import QImage
from PySide6.QtCore import QRectF

from ..base.capture import CaptureBackend
from .permissions import MacOSPermissionBackend, _cg_preflight


class ScreenCapturePermissionError(RuntimeError):
    """屏幕录制权限未授予。"""

    def __init__(self):
        super().__init__("macOS 屏幕录制权限未授予")


class MacOSCaptureBackend(CaptureBackend):
    """macOS 截图后端。"""

    def is_available(self) -> bool:
        return _cg_preflight()

    def capture_all_screens(self) -> Tuple[QImage, QRectF]:
        if not _cg_preflight():
            raise ScreenCapturePermissionError()

        with mss.mss() as sct:
            monitors = sct.monitors
            all_monitors = monitors[0]
            screenshot = sct.grab(all_monitors)

            img_width = screenshot.width
            img_height = screenshot.height
            bytes_per_line = img_width * 4
            qimage = QImage(
                screenshot.bgra, img_width, img_height,
                bytes_per_line, QImage.Format.Format_RGB32,
            )
            original_image = qimage.copy()

            rect = QRectF(
                all_monitors['left'], all_monitors['top'],
                all_monitors['width'], all_monitors['height'],
            )
            return original_image, rect
