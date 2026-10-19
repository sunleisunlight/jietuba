# -*- coding: utf-8 -*-
"""Windows 输入后端 — GetAsyncKeyState 按键状态 + mouse_event 滚轮。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Tuple

from ..base.input import InputBackend

_user32 = ctypes.windll.user32

#: 鼠标按键虚拟键码
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02

MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120

_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                wintypes.DWORD, ctypes.c_void_p]
_user32.mouse_event.restype = None


class WindowsInputBackend(InputBackend):
    """Windows 输入后端。"""

    def pointer_buttons(self) -> Tuple[bool, bool]:
        left = bool(_user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        right = bool(_user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
        return left, right

    def send_scroll(self, dx_lines: int = 0, dy_lines: int = 0) -> bool:
        try:
            if dy_lines:
                _user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0,
                                    int(dy_lines) * WHEEL_DELTA, None)
            if dx_lines:
                _user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0,
                                    int(dx_lines) * WHEEL_DELTA, None)
            return True
        except Exception:
            return False
