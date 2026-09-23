# -*- coding: utf-8 -*-
"""屏幕捕获后端 — 统一截图接口。

Windows / macOS 第一版均以 mss 为静态截图实现（mss 自带双平台支持），
但权限检测、权限引导、黑屏兜底等行为按平台分派到各子类。
GIF 录屏不经过本后端（走 Rust gifrecorder 的 native capture）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple

from PySide6.QtGui import QImage
from PySide6.QtCore import QRectF


class CaptureBackend(ABC):
    """平台截图后端统一接口。"""

    @abstractmethod
    def capture_all_screens(self) -> Tuple[QImage, QRectF]:
        """捕获整个虚拟桌面，返回 (QImage, QRectF(虚拟桌面几何))。

        QImage 为物理像素分辨率；QRectF 使用虚拟桌面坐标（可能含负值）。
        """

    def is_available(self) -> bool:
        """截图能力是否可用（权限已授予等）。默认 True。"""
        return True
