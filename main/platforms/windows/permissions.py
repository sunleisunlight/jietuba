# -*- coding: utf-8 -*-
"""Windows 权限后端 — 无系统截图/辅助功能权限概念，全部返回不适用。"""
from __future__ import annotations

import os
import subprocess

from ..base.permissions import PermissionBackend, PermissionStatus


class WindowsPermissionBackend(PermissionBackend):
    """Windows 权限后端。"""

    def screen_capture_status(self) -> PermissionStatus:
        return PermissionStatus.GRANTED

    def accessibility_status(self) -> PermissionStatus:
        return PermissionStatus.GRANTED

    def input_monitoring_status(self) -> PermissionStatus:
        return PermissionStatus.GRANTED

    def open_system_settings(self, permission: str) -> None:
        # Windows 无对应系统设置面板，打开隐私设置页兜底
        try:
            subprocess.Popen(["start", "ms-settings:privacy"], shell=True)
        except Exception:
            pass
