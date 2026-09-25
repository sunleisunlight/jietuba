# -*- coding: utf-8 -*-
"""系统权限后端 — 统一权限检查/请求/引导接口。

Windows 没有截图/辅助功能权限概念（返回 granted/不需要）；
macOS 实现屏幕录制、辅助功能、输入监控三类权限。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class PermissionStatus(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    NOT_REQUESTED = "not_requested"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class PermissionBackend(ABC):
    """平台权限后端。"""

    # ── 屏幕录制（截图 / GIF 录屏）──
    @abstractmethod
    def screen_capture_status(self) -> PermissionStatus:
        """屏幕录制权限状态。"""

    def request_screen_capture(self) -> bool:
        """请求屏幕录制权限（弹出系统授权框）；返回是否已授予。"""
        return self.screen_capture_status() == PermissionStatus.GRANTED

    # ── 辅助功能（AXUIElement / UIA 控件级）──
    @abstractmethod
    def accessibility_status(self) -> PermissionStatus:
        """辅助功能权限状态。"""

    def request_accessibility(self) -> bool:
        """请求辅助功能权限。"""
        return self.accessibility_status() == PermissionStatus.GRANTED

    # ── 输入监控（键盘/鼠标监听、侧键、模拟按键）──
    def input_monitoring_status(self) -> PermissionStatus:
        """输入监控权限状态。默认不适用。"""
        return PermissionStatus.NOT_APPLICABLE

    # ── 系统设置引导 ──
    @abstractmethod
    def open_system_settings(self, permission: str) -> None:
        """打开对应权限的系统设置面板。permission: screen_capture/accessibility/input_monitoring。"""
