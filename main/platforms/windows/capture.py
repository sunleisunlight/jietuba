# -*- coding: utf-8 -*-
"""Windows 屏幕捕获后端 — 沿用 mss 实现（与历史 CaptureService 一致）。"""
from __future__ import annotations

from typing import Tuple

import mss
from PySide6.QtGui import QImage
from PySide6.QtCore import QRectF

from ..base.capture import CaptureBackend


class WindowsCaptureBackend(CaptureBackend):
    """Windows 截图后端：mss 捕获虚拟桌面。"""

    def capture_all_screens(self) -> Tuple[QImage, QRectF]:
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
