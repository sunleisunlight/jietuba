# -*- coding: utf-8 -*-
"""剪贴板后端 — 统一剪贴板写入与粘贴接口。

Windows 保留 Win32 CF_DIBV5/PNG/CF_HDROP 原生实现；
macOS 使用 NSPasteboard / Qt clipboard，粘贴时以 Command+V 注入。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from PySide6.QtGui import QImage


class ClipboardBackend(ABC):
    """平台剪贴板后端。"""

    @abstractmethod
    def copy_image(self, image: QImage, file_reference: Optional[str] = None) -> None:
        """把 QImage（及可选的文件路径引用）写入系统剪贴板。"""

    def paste_to_target(self, target: object) -> None:
        """把焦点还给目标窗口/应用后补发粘贴快捷键（Windows=Ctrl+V，Mac=Command+V）。

        target 为 None 时按当前前台窗口处理。默认实现：不处理。
        """
