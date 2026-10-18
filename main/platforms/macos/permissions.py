# -*- coding: utf-8 -*-
"""macOS 权限后端 — 屏幕录制 / 辅助功能 / 输入监控。

实现：
  屏幕录制  CGPreflightScreenCaptureAccess / CGRequestScreenCaptureAccess
             （Quartz，macOS 10.15+；两者均在主线程调用）
  辅助功能  AXIsProcessTrusted / AXIsProcessTrustedWithOptions
  输入监控  CGPreflightListenEventAccess / CGRequestListenEventAccess
            查询不创建监听、不弹框，也不改变系统权限。
"""
from __future__ import annotations

import subprocess
import logging

from ..base.permissions import PermissionBackend, PermissionStatus

_log = logging.getLogger(__name__)


def _cg_preflight() -> bool:
    """屏幕录制权限是否已授予（CGPreflightScreenCaptureAccess）。"""
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        _log.exception("读取屏幕录制权限失败")
        raise


def _cg_request() -> None:
    """弹出系统屏幕录制授权框（CGRequestScreenCaptureAccess）。"""
    try:
        from Quartz import CGRequestScreenCaptureAccess
        CGRequestScreenCaptureAccess()
    except Exception:
        _log.exception("请求屏幕录制权限失败")


def _ax_is_trusted() -> bool:
    """辅助功能权限是否已授予。"""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        _log.exception("读取辅助功能权限失败")
        raise


def _ax_is_trusted_with_options() -> bool:
    """带提示的辅助功能检查（首次会弹系统提示）。"""
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        return bool(AXIsProcessTrustedWithOptions(
            {kAXTrustedCheckOptionPrompt: True}
        ))
    except Exception:
        _log.exception("请求辅助功能权限失败")
        return False


def _input_monitoring_status() -> PermissionStatus:
    """只读权限查询，不创建 EventTap，不手动释放 PyObjC 管理的对象。"""
    try:
        from Quartz import CGPreflightListenEventAccess
        if CGPreflightListenEventAccess():
            return PermissionStatus.GRANTED
        return PermissionStatus.DENIED
    except Exception:
        _log.exception("读取输入监控权限失败")
        return PermissionStatus.UNKNOWN


class MacOSPermissionBackend(PermissionBackend):
    """macOS 权限后端。"""

    def screen_capture_status(self) -> PermissionStatus:
        try:
            return PermissionStatus.GRANTED if _cg_preflight() else PermissionStatus.DENIED
        except Exception:
            return PermissionStatus.UNKNOWN

    def request_screen_capture(self) -> bool:
        _cg_request()
        return _cg_preflight()

    def accessibility_status(self) -> PermissionStatus:
        try:
            return PermissionStatus.GRANTED if _ax_is_trusted() else PermissionStatus.DENIED
        except Exception:
            return PermissionStatus.UNKNOWN

    def request_accessibility(self) -> bool:
        _ax_is_trusted_with_options()
        return _ax_is_trusted()

    def input_monitoring_status(self) -> PermissionStatus:
        return _input_monitoring_status()

    def request_input_monitoring(self) -> bool:
        try:
            from Quartz import CGRequestListenEventAccess
            return bool(CGRequestListenEventAccess())
        except Exception:
            _log.exception("请求输入监控权限失败")
            return False

    def open_system_settings(self, permission: str) -> None:
        pane = "com.apple.preference.security?Privacy_ScreenCapture"
        if permission == "accessibility":
            pane = "com.apple.preference.security?Privacy_Accessibility"
        elif permission == "input_monitoring":
            pane = "com.apple.preference.security?Privacy_ListenEvent"
        try:
            subprocess.Popen(["open", f"x-apple.systempreferences:{pane}"])
        except Exception:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security"])
