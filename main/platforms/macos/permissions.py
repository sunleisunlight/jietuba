# -*- coding: utf-8 -*-
"""macOS 权限后端 — 屏幕录制 / 辅助功能 / 输入监控。

实现：
  屏幕录制  CGPreflightScreenCaptureAccess / CGRequestScreenCaptureAccess
             （Quartz，macOS 10.15+；两者均在主线程调用）
  辅助功能  AXIsProcessTrusted / AXIsProcessTrustedWithOptions
  输入监控  无公开查询 API，用临时 CGEventTap 探测代替
            （tap 创建失败/被拒绝 ≈ 未授权）
"""
from __future__ import annotations

import subprocess

from ..base.permissions import PermissionBackend, PermissionStatus


def _cg_preflight() -> bool:
    """屏幕录制权限是否已授予（CGPreflightScreenCaptureAccess）。"""
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return False


def _cg_request() -> None:
    """弹出系统屏幕录制授权框（CGRequestScreenCaptureAccess）。"""
    try:
        from Quartz import CGRequestScreenCaptureAccess
        CGRequestScreenCaptureAccess()
    except Exception:
        pass


def _ax_is_trusted() -> bool:
    """辅助功能权限是否已授予。"""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


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
        return False


def _input_monitoring_status() -> PermissionStatus:
    """输入监控状态探测：用 CGEventTap 是否能正常创建监听。

    macOS 10.15+ 对键盘事件 tap 要求"输入监控"，鼠标事件 tap 要求"辅助功能"。
    无公开权限查询 API，只能通过 tap 创建结果反推。
    """
    try:
        import Quartz
        from Quartz import (
            CGEventMaskBit,
            CGEventTapCreate,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            kCGSessionEventTap,
        )

        mask = CGEventMaskBit(Quartz.kCGEventKeyDown) | CGEventMaskBit(Quartz.kCGEventKeyUp)
        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly, mask, None, None,
        )
        if tap is not None:
            Quartz.CFRelease(tap)
            return PermissionStatus.GRANTED
        return PermissionStatus.DENIED
    except Exception:
        return PermissionStatus.UNKNOWN


class MacOSPermissionBackend(PermissionBackend):
    """macOS 权限后端。"""

    def screen_capture_status(self) -> PermissionStatus:
        if _cg_preflight():
            return PermissionStatus.GRANTED
        return PermissionStatus.NOT_REQUESTED

    def request_screen_capture(self) -> bool:
        _cg_request()
        return _cg_preflight()

    def accessibility_status(self) -> PermissionStatus:
        if _ax_is_trusted():
            return PermissionStatus.GRANTED
        return PermissionStatus.NOT_REQUESTED

    def request_accessibility(self) -> bool:
        _ax_is_trusted_with_options()
        return _ax_is_trusted()

    def input_monitoring_status(self) -> PermissionStatus:
        return _input_monitoring_status()

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
