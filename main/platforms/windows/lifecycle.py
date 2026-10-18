"""Windows login registry and native taskbar icon implementation."""
from pathlib import Path
import sys

from ..base.lifecycle import LifecycleBackend


class WindowsLifecycleBackend(LifecycleBackend):
    key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    name = "JileiScreenshot"

    def autostart_enabled(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
                winreg.QueryValueEx(key, self.name)
            return True
        except FileNotFoundError:
            return False

    def set_autostart(self, enabled):
        import subprocess
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                args = [sys.executable]
                if not getattr(sys, "frozen", False):
                    args.append(str(Path(__file__).resolve().parents[2] / "main_app.py"))
                winreg.SetValueEx(key, self.name, 0, winreg.REG_SZ, subprocess.list2cmdline(args))
            else:
                try:
                    winreg.DeleteValue(key, self.name)
                except FileNotFoundError:
                    return  # Already disabled, not a failure.

    def apply_window_icon(self, widget, icon):
        import ctypes
        from ctypes import wintypes
        import tempfile
        super().apply_window_icon(widget, icon)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                     wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.DestroyIcon.argtypes = [wintypes.HANDLE]
        with tempfile.TemporaryDirectory(prefix="jilei-icon-") as temp:
            path = str(Path(temp) / "icon.ico")
            if not icon.pixmap(32, 32).save(path, "ICO"):
                raise RuntimeError("无法生成任务栏图标")
            handle = user32.LoadImageW(None, path, 1, 32, 32, 0x10)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        user32.SendMessageW(int(widget.winId()), 0x80, 1, handle)
        user32.SendMessageW(int(widget.winId()), 0x80, 0, handle)
        previous = getattr(widget, "_native_icon_handle", None)
        if previous:
            user32.DestroyIcon(previous)
        widget._native_icon_handle = handle
        widget.destroyed.connect(lambda: user32.DestroyIcon(handle) if widget._native_icon_handle == handle else None)
