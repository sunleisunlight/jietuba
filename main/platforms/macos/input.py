# -*- coding: utf-8 -*-
"""macOS 输入后端 — CGEventSourceButtonState 按键状态 + CGEvent 滚轮。

滚轮事件语义与 pynput 一致：正值 = 向上 / 向右。
"""
from __future__ import annotations

import logging
from typing import Tuple

from ..base.input import InputBackend

_log = logging.getLogger(__name__)


class MacOSInputBackend(InputBackend):
    """macOS 输入后端（Quartz CGEvent）。"""

    def pointer_buttons(self) -> Tuple[bool, bool]:
        try:
            import Quartz
            state = Quartz.kCGEventSourceStateCombinedSessionState
            left = bool(Quartz.CGEventSourceButtonState(state, 0))
            right = bool(Quartz.CGEventSourceButtonState(state, 1))
            return left, right
        except Exception:
            _log.exception("读取 macOS 指针按键状态失败")
            return False, False

    def send_scroll(self, dx_lines: int = 0, dy_lines: int = 0) -> bool:
        try:
            import Quartz
            if dx_lines:
                # wheelCount=2：wheel1=垂直，wheel2=水平
                ev = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitLine, 2, int(dy_lines), int(dx_lines))
            else:
                ev = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitLine, 1, int(dy_lines))
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            return True
        except Exception:
            _log.exception("投递 macOS 滚轮事件失败")
            return False
