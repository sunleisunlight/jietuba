# -*- coding: utf-8 -*-
"""平台抽象层（platforms）— 统一 Windows / macOS 系统能力入口。

设计目标：
  业务代码不直接出现 ``if sys.platform == ...``，全部经
  ``get_platform_backend()`` 获取当前平台后端，再调用统一接口。
  现有 Windows 原生实现（Win32/UIA/COM）搬入 ``platforms.windows``，
  macOS 实现放 ``platforms.macos``，两者实现同一个 base 接口。

注意：刻意不叫 ``platform``，避免遮蔽 Python 标准库 ``platform``。
"""
import sys

from .factory import PlatformFactory

_backend = None


def get_platform_backend():
    """返回当前平台后端单例（工厂惰性构建）。"""
    global _backend
    if _backend is None:
        _backend = PlatformFactory().create()
    return _backend


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


__all__ = ["get_platform_backend", "is_windows", "is_macos"]
