# -*- coding: utf-8 -*-
"""输入后端 — 合成滚轮事件与指针按键状态。

长截图横向模式需要向系统投递滚轮事件（Windows ``mouse_event`` /
macOS ``CGEventPost``）；GIF 录制的光标图层需要读取指针左右键状态
（Windows ``GetAsyncKeyState`` / macOS ``CGEventSourceButtonState``）。

两者都是「只能由操作系统提供」的能力，因此按平台分实现，业务模块
（``main/stitch``、``main/gif``）只调用本接口，不再自行判断平台。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple


class InputBackend(ABC):
    """平台输入后端统一接口。"""

    @abstractmethod
    def pointer_buttons(self) -> Tuple[bool, bool]:
        """当前指针按键状态，返回 ``(left_down, right_down)``。"""

    @abstractmethod
    def send_scroll(self, dx_lines: int = 0, dy_lines: int = 0) -> bool:
        """向系统投递滚轮事件（正值 = 上/右，与 pynput 一致）。

        返回是否成功投递；失败由调用方记录日志，不抛出。
        """
