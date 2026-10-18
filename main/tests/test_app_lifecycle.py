"""Lifecycle regression tests use isolated locks, settings and login registration."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.instance_broker import InstanceBroker


@pytest.mark.parametrize("activate", [True, False])
def test_second_process_acknowledges_without_replacing_owner(qapp, tmp_path, activate):
    owner = InstanceBroker(directory=tmp_path, identity="test")
    assert owner.acquire()
    calls = []
    owner.activate_requested.connect(lambda: calls.append(True))
    script = (
        "from PySide6.QtCore import QCoreApplication; "
        "from core.instance_broker import InstanceBroker; "
        "a=QCoreApplication([]); "
        f"b=InstanceBroker(directory={str(tmp_path)!r},identity='test'); "
        f"assert b.acquire(activate={activate!r}) is False"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    try:
        child = subprocess.Popen([sys.executable, "-c", script], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while child.poll() is None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.005)
        if child.poll() is None:
            child.kill()
            pytest.fail("Secondary process timed out")
        stdout, stderr = child.communicate()
        assert child.returncode == 0, (stdout, stderr)
        assert calls == ([True] if activate else [])
        assert owner.server.isListening()
        assert owner.lock.isLocked()
    finally:
        owner.close()


def test_lock_released_on_clean_exit(qapp, tmp_path):
    first = InstanceBroker(directory=tmp_path, identity="test")
    assert first.acquire()
    first.close()
    second = InstanceBroker(directory=tmp_path, identity="test")
    try:
        assert second.acquire()
    finally:
        second.close()


def test_unresponsive_owner_is_not_killed(qapp, tmp_path):
    from PySide6.QtCore import QLockFile
    candidate = InstanceBroker(directory=tmp_path, identity="test")
    lock = QLockFile(str(tmp_path / (candidate.name + ".lock")))
    assert lock.tryLock(0)
    try:
        with pytest.raises(RuntimeError, match="不会终止"):
            candidate.acquire()
        assert lock.isLocked()
    finally:
        lock.unlock()


def test_dead_owner_lock_recovered(qapp, tmp_path):
    broker = InstanceBroker(directory=tmp_path, identity="test")
    # QLockFile's documented on-disk PID/application/hostname representation.
    path = tmp_path / (broker.name + ".lock")
    path.write_text("2147483647\nnonexistent-jilei-test\n\n")
    try:
        assert broker.acquire()
    finally:
        broker.close()


def test_legacy_process_is_preserved(monkeypatch, tmp_path):
    from core import instance_broker, platform_utils
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/synthetic/JileiScreenshot")
    monkeypatch.setattr(instance_broker.tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / "JileiScreenshot.pid").write_text("98765\n98765\n")
    monkeypatch.setattr(platform_utils, "get_process_identity", lambda pid: (98765, "JileiScreenshot"))
    with pytest.raises(RuntimeError, match="旧版"):
        instance_broker.refuse_legacy_owner()
    monkeypatch.setattr(platform_utils, "get_process_identity", lambda pid: (98765, "unrelated"))
    instance_broker.refuse_legacy_owner()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS lifecycle backend")
def test_launch_agent_is_escaped_quiet_and_reversible(tmp_path):
    from platforms.macos.lifecycle import MacOSLifecycleBackend
    path = tmp_path / "login.plist"
    program = ["/Applications/Test & 中文.app/Contents/MacOS/JileiScreenshot"]
    backend = MacOSLifecycleBackend(agent_path=path, program=program)
    assert not backend.autostart_enabled()
    backend.set_autostart(True)
    assert backend.autostart_enabled()
    data = plistlib.loads(path.read_bytes())
    assert data["ProgramArguments"] == [*program, "--autostart"]
    assert data["Label"] == "cc.jilei.jileiscreenshot"
    assert backend.show_on_manual_launch()
    backend.set_autostart(False)
    assert not backend.autostart_enabled()
    backend.set_autostart(False)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS lifecycle backend")
def test_launch_agent_write_failure_is_not_success(tmp_path):
    from platforms.macos.lifecycle import MacOSLifecycleBackend
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    backend = MacOSLifecycleBackend(agent_path=blocker / "login.plist")
    with pytest.raises(OSError):
        backend.set_autostart(True)


@pytest.mark.skipif(sys.platform != "darwin", reason="Cocoa native delegate integration")
def test_cocoa_reopen_retains_qt_delegate(qapp):
    from AppKit import NSApplication
    from platforms.macos.lifecycle import MacOSLifecycleBackend
    app = NSApplication.sharedApplication()
    original = app.delegate()
    calls = []
    backend = MacOSLifecycleBackend()
    backend.install_reopen_handler(lambda: calls.append(True))
    assert app.delegate() == original
    assert original.applicationShouldHandleReopen_hasVisibleWindows_(app, False)
    assert calls == [True]


@pytest.mark.parametrize("modal", [True, False])
def test_reopen_preserves_active_editor(qapp, modal):
    from main_app import MainApp
    window = Mock()
    window.isVisible.return_value = True
    fake = SimpleNamespace(lifecycle=Mock(), app=Mock(), screenshot_window=window,
                           open_settings=Mock())
    fake.app.activeModalWidget.return_value = window if modal else None
    MainApp.activate_existing(fake)
    window.raise_.assert_called_once()
    window.activateWindow.assert_called_once()
    fake.open_settings.assert_not_called()


def test_reopen_after_window_closed_opens_settings(qapp):
    from main_app import MainApp
    fake = SimpleNamespace(lifecycle=Mock(), app=Mock(), screenshot_window=None,
                           open_settings=Mock(), _preloader=Mock())
    fake.app.activeModalWidget.return_value = None
    MainApp.activate_existing(fake)
    fake.open_settings.assert_called_once()


@pytest.mark.parametrize("first,quiet,manual,expected", [
    (False, False, True, 1), (False, True, True, 0),
    (False, False, False, 0), (True, False, True, 0),
])
def test_startup_policy(qapp, monkeypatch, first, quiet, manual, expected):
    from core.bootstrap import PreloadManager
    from platforms import factory
    import ui.welcome
    monkeypatch.setattr(sys, "argv", ["app", "--autostart"] if quiet else ["app"])
    monkeypatch.setattr(factory, "get_lifecycle_backend", lambda: SimpleNamespace(
        show_on_manual_launch=lambda: manual))
    wizard = Mock()
    monkeypatch.setattr(ui.welcome, "WelcomeWizard", lambda config: wizard)
    config = Mock()
    config.is_first_run.return_value = first
    config.should_show_main_window_on_start.return_value = False
    app = Mock(config_manager=config)
    preloader = PreloadManager(app)
    preloader._preload_clipboard_window = Mock()
    preloader._show_main_window_on_start()
    assert app.open_settings.call_count == expected
    assert wizard.exec.call_count == int(first)
    config.mark_as_run.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native icon regression")
def test_windows_taskbar_icon(qapp):
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from PySide6.QtWidgets import QWidget
    from platforms.windows.lifecycle import WindowsLifecycleBackend
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("red"))
    window = QWidget()
    WindowsLifecycleBackend().apply_window_icon(window, QIcon(pixmap))
    assert window._native_icon_handle
    window.deleteLater()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native Unicode shell link")
def test_windows_unicode_shortcut_roundtrip(tmp_path):
    import comtypes
    from comtypes.persist import IPersistFile
    from comtypes.shelllink import IShellLinkW, ShellLink
    from platforms.windows.lifecycle import WindowsLifecycleBackend

    folder = tmp_path / "中文 & user's folder"
    folder.mkdir()
    target = folder / "积磊截图.exe"
    target.write_bytes(b"test fixture; never executed")
    shortcut = folder / "积磊截图.lnk"
    arguments = '--sample "测试 & quote"'
    WindowsLifecycleBackend().create_executable_shortcut(
        shortcut, target, arguments=arguments, working_directory=folder)
    # Read the actual saved link through Unicode COM, not merely file existence.
    link = comtypes.CoCreateInstance(ShellLink._reg_clsid_, interface=IShellLinkW)
    link.QueryInterface(IPersistFile).Load(str(shortcut), 0)
    assert Path(link.GetPath(0)) == target
    assert Path(link.GetWorkingDirectory()) == folder
    assert link.GetArguments() == arguments
    assert Path(link.GetIconLocation()[0]) == target


def test_onefile_keeps_lifecycle_native_dependencies():
    import ast
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "build_with_ocr_onefile.py").read_text(encoding="utf-8-sig"))
    lists = {target.id: ast.literal_eval(node.value)
             for node in tree.body if isinstance(node, ast.Assign)
             for target in node.targets if isinstance(target, ast.Name)
             and target.id in ("hiddenimports", "hidden_imports", "excludes")}
    assert "PySide6.QtNetwork" not in lists["excludes"]
    hidden = lists.get("hiddenimports", lists.get("hidden_imports", []))
    assert {"PySide6.QtNetwork", "comtypes.shelllink", "comtypes.persist"} <= set(hidden)
