# -*- coding: utf-8 -*-
"""平台后端工厂 — 按当前系统选择 Windows / macOS 后端。

每个后端提供一组职责单一的子后端（capture/hotkey/clipboard/window/
accessibility/coordinates/permissions），业务代码通过
``backend.<name>.<method>()`` 调用，平台差异只存在于本包内部。
"""
import sys

from .base.capture import CaptureBackend
from .base.hotkey import GlobalHotkeyBackend
from .base.clipboard import ClipboardBackend
from .base.window import WindowBackend
from .base.accessibility import AccessibilityBackend
from .base.coordinates import CoordinateMapper
from .base.permissions import PermissionBackend


class PlatformBackend:
    """聚合子后端的容器对象（鸭子类型，无继承要求）。"""

    def __init__(self, *, capture, hotkey, clipboard, window,
                 accessibility, coordinates, permissions):
        self.capture = capture
        self.hotkeys = hotkey
        self.clipboard = clipboard
        self.windows = window
        self.accessibility = accessibility
        self.coordinates = coordinates
        self.permissions = permissions

    @property
    def is_windows(self) -> bool:
        return sys.platform == "win32"

    @property
    def is_macos(self) -> bool:
        return sys.platform == "darwin"


class PlatformFactory:
    """惰性选择并组装当前平台的 backend 集合。"""

    def create(self) -> PlatformBackend:
        if sys.platform == "win32":
            from .windows.capture import WindowsCaptureBackend
            from .windows.hotkey import WindowsHotkeyBackend
            from .windows.clipboard import WindowsClipboardBackend
            from .windows.window import WindowsWindowBackend
            from .windows.accessibility import WindowsAccessibilityBackend
            from .windows.coordinates import WindowsCoordinateMapper
            from .windows.permissions import WindowsPermissionBackend
            return PlatformBackend(
                capture=WindowsCaptureBackend(),
                hotkey=WindowsHotkeyBackend(),
                clipboard=WindowsClipboardBackend(),
                window=WindowsWindowBackend(),
                accessibility=WindowsAccessibilityBackend(),
                coordinates=WindowsCoordinateMapper(),
                permissions=WindowsPermissionBackend(),
            )
        if sys.platform == "darwin":
            from .macos.capture import MacOSCaptureBackend
            from .macos.hotkey import MacOSHotkeyBackend
            from .macos.clipboard import MacOSClipboardBackend
            from .macos.window import MacOSWindowBackend
            from .macos.accessibility import MacOSAccessibilityBackend
            from .macos.coordinates import MacOSCoordinateMapper
            from .macos.permissions import MacOSPermissionBackend
            return PlatformBackend(
                capture=MacOSCaptureBackend(),
                hotkey=MacOSHotkeyBackend(),
                clipboard=MacOSClipboardBackend(),
                window=MacOSWindowBackend(),
                accessibility=MacOSAccessibilityBackend(),
                coordinates=MacOSCoordinateMapper(),
                permissions=MacOSPermissionBackend(),
            )
        raise RuntimeError(f"不支持的平台: {sys.platform}")
