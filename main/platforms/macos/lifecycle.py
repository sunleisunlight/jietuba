"""Cocoa Dock reopening and LaunchAgent registration, keeping bundle identity."""
from pathlib import Path
import os
import plistlib
import sys
import tempfile

from ..base.lifecycle import LifecycleBackend


class MacOSLifecycleBackend(LifecycleBackend):
    label = "cc.jilei.jileiscreenshot"

    def __init__(self, *, agent_path=None, program=None):
        self.agent_path = Path(agent_path) if agent_path else (
            Path.home() / "Library/LaunchAgents" / f"{self.label}.plist")
        self.program = program
        self._reopen = None

    def show_on_manual_launch(self):
        return True

    def install_reopen_handler(self, callback):
        import objc
        from AppKit import NSApplication
        delegate = NSApplication.sharedApplication().delegate()
        if delegate is None:
            raise RuntimeError("Cocoa application delegate 尚未建立")

        def reopen(_delegate, _application, _visible):
            callback()
            return True

        # Extend Qt's delegate rather than replacing it: retain its quit/menu/file handlers.
        self._reopen = objc.selector(
            reopen, selector=b"applicationShouldHandleReopen:hasVisibleWindows:",
            signature=b"B@:@B")
        objc.classAddMethods(type(delegate), [self._reopen])

    def activate(self):
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def restart_app(self) -> bool:
        """退出当前进程并重新打开本 .app。

        屏幕录制 / 辅助功能的 TCC 授权只在下次进程启动时生效，用户点完
        「已完成」如果仍在拒绝，唯一的正经解法就是重启，这里直接代劳。
        延迟 1 秒再 open，保证旧进程已经释放单实例锁。
        """
        import subprocess

        bundle = self._app_bundle()
        if bundle is None:
            return False
        try:
            subprocess.Popen(
                ["/bin/sh", "-c", 'sleep 1; exec /usr/bin/open -n "$1"',
                 "jilei-restart", str(bundle)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            )
        except Exception:
            return False
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
        return True

    def _app_bundle(self):
        """从可执行文件回溯到 .app 包；开发环境（python 直跑）返回 None。"""
        if not getattr(sys, "frozen", False):
            return None
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
        return None

    def autostart_enabled(self):
        if not self.agent_path.exists():
            return False
        with self.agent_path.open("rb") as stream:
            entry = plistlib.load(stream)
        return entry.get("Label") == self.label and bool(entry.get("RunAtLoad"))

    def set_autostart(self, enabled):
        if not enabled:
            self.agent_path.unlink(missing_ok=True)
            return
        program = self.program
        if program is None:
            program = [sys.executable]
            if not getattr(sys, "frozen", False):
                program.append(str(Path(__file__).resolve().parents[2] / "main_app.py"))
        entry = {"Label": self.label, "ProgramArguments": [*program, "--autostart"],
                 "RunAtLoad": True, "ProcessType": "Interactive"}
        self.agent_path.parent.mkdir(parents=True, exist_ok=True)
        # plistlib escapes ampersands/angle brackets in app/user paths. Atomic write.
        fd, temporary = tempfile.mkstemp(dir=self.agent_path.parent, prefix=".jilei-")
        try:
            with os.fdopen(fd, "wb") as stream:
                plistlib.dump(entry, stream)
            os.replace(temporary, self.agent_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
