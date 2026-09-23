# -*- coding: utf-8 -*-
"""全局快捷键后端 — 统一注册/注销/可用性探测接口。

快捷键字符串格式全平台统一（如 "ctrl+shift+a"、"win+1"、"mouseback"），
各平台后端负责把字符串翻译成系统级热键并注册。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional


class GlobalHotkeyBackend(ABC):
    """系统级全局热键后端。"""

    @abstractmethod
    def register(self, hotkey_id: int, hotkey_str: str, callback: Callable[[], None]) -> bool:
        """注册热键；成功返回 True，占用/非法返回 False。

        callback 在主线程被调用（Windows 走原生事件过滤器，
        macOS 走 Carbon 事件处理器）。
        """

    @abstractmethod
    def unregister(self, hotkey_id: int) -> None:
        """注销单个热键。"""

    @abstractmethod
    def unregister_all(self) -> None:
        """注销全部热键。"""

    @abstractmethod
    def check_available(self, hotkey_str: str) -> bool:
        """探测快捷键是否可用（临时注册再注销）。"""

    def install_native_filter(self, app) -> Optional[object]:
        """安装平台原生事件过滤器（如 Windows WM_HOTKEY 过滤器）。

        没有原生过滤器概念的平台返回 None。
        """
        return None
