# -*- coding: utf-8 -*-
"""应用内更新交互测试。

重点回归：更新检查在后台线程跑，但**弹窗必须建在 GUI 线程**。
以前把后台线程的信号连到了普通闭包，槽在后台线程里执行，弹窗创建在非 GUI 线程上，
表现就是用户点「检查更新」什么都不弹。
"""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QPushButton

import ui.update_flow as update_flow
from ui.settings_ui import page_about


def _reset_controller(monkeypatch):
    """每个用例拿一个干净的控制器（模块级单例会跨用例复用）。"""
    monkeypatch.setattr(update_flow, "_controller", None)
    return update_flow.get_update_controller()


@pytest.fixture
def restore_skipped_version():
    original = update_flow.skipped_update_version()
    yield
    update_flow.skip_update_version(original)


def _fake_info(version: str = "9.9.9"):
    return update_flow.updater.UpdateInfo(
        version=version, notes="修复若干问题", url="https://cc.jilei.cc/a.exe",
        sha256="a" * 64, size=1_048_576,
    )


class TestUpdateCheckThreading:
    def test_manual_check_reports_latest_on_gui_thread(self, monkeypatch, qapp, qtbot):
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: None)
        calls = []
        monkeypatch.setattr(
            update_flow, "show_info_dialog",
            lambda *args: calls.append((args, QThread.currentThread())),
        )
        controller = _reset_controller(monkeypatch)

        assert controller.check(silent=False) is True
        qtbot.waitUntil(lambda: bool(calls), timeout=5000)

        _, thread = calls[0]
        assert thread is qapp.thread()          # 弹窗必须在 GUI 线程
        assert update_flow.APP_VERSION in calls[0][0][2]

    def test_manual_check_offers_new_version_on_gui_thread(self, monkeypatch, qapp, qtbot):
        info = _fake_info()
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: info)
        shown = []

        class _FakeDialog:
            def __init__(self, parent, info):
                shown.append((parent, info, QThread.currentThread()))

            def exec(self):
                return 1

        monkeypatch.setattr(update_flow, "_UpdateDialog", _FakeDialog)
        controller = _reset_controller(monkeypatch)

        assert controller.check(silent=False) is True
        qtbot.waitUntil(lambda: bool(shown), timeout=5000)

        _, shown_info, thread = shown[0]
        assert shown_info is info
        assert thread is qapp.thread()

    def test_silent_check_is_quiet_and_respects_skip(
        self, monkeypatch, qapp, qtbot, restore_skipped_version
    ):
        info = _fake_info("9.9.9")
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: info)
        shown = []
        monkeypatch.setattr(update_flow, "show_info_dialog", lambda *a: shown.append(a))

        class _FakeDialog:
            def __init__(self, parent, info):
                shown.append((parent, info))

            def exec(self):
                return 1

        monkeypatch.setattr(update_flow, "_UpdateDialog", _FakeDialog)
        controller = _reset_controller(monkeypatch)

        # 静默检查：无更新 / 网络失败一律不打扰
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: None)
        controller.check(silent=True)
        qtbot.waitUntil(lambda: not controller.is_checking, timeout=5000)
        assert shown == []

        # 用户点过「跳过此版本」后，静默检查不再提示
        update_flow.skip_update_version("9.9.9")
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: info)
        controller.check(silent=True)
        qtbot.waitUntil(lambda: not controller.is_checking, timeout=5000)
        assert shown == []

        # 手动检查仍然提示（跳过的只是后台打扰，不是永久屏蔽）
        controller.check(silent=False)
        qtbot.waitUntil(lambda: bool(shown), timeout=5000)
        assert len(shown) == 1

    def test_failed_check_does_not_block_next_check(self, monkeypatch, qapp, qtbot):
        def _boom():
            raise RuntimeError("network down")

        monkeypatch.setattr(update_flow.updater, "check_for_update", _boom)
        calls = []
        monkeypatch.setattr(update_flow, "show_info_dialog", lambda *a: calls.append(a))
        controller = _reset_controller(monkeypatch)

        controller.check(silent=False)
        qtbot.waitUntil(lambda: bool(calls), timeout=5000)
        # 线程异常也必须归还忙碌态，按钮不能卡在「检查中」
        qtbot.waitUntil(lambda: not controller.is_checking, timeout=5000)


class TestAboutPageCheckButton:
    def test_button_busy_state_follows_controller(self, monkeypatch, qapp, qtbot):
        gate = threading.Event()

        def _slow_check():
            gate.wait(5)
            return None

        monkeypatch.setattr(update_flow.updater, "check_for_update", _slow_check)
        monkeypatch.setattr(update_flow, "show_info_dialog", lambda *a: None)
        controller = _reset_controller(monkeypatch)

        dialog = QDialog()
        page = page_about.create_about_page(dialog)
        button = page.findChild(QPushButton, "checkUpdateButton")
        assert button.text() == "Check for Updates"

        button.click()
        assert button.text() == "Checking..."
        assert not button.isEnabled()

        gate.set()
        qtbot.waitUntil(lambda: not controller.is_checking, timeout=5000)
        assert button.isEnabled()
        assert button.text() == "Check for Updates"
        page.deleteLater()
        dialog.deleteLater()


class TestInstallAndRestart:
    """点「立即更新」必须真的把新 exe 覆盖到原路径。

    回归：以前靠写 .bat「等进程退出再 move 覆盖」，bat 里带中文路径、按 GBK 写出
    却被 cmd 按 UTF-8 解析，move 静默失败 —— 更新包下载校验都成功，版本却还是旧的。
    """

    def _fake_exe(self, tmp_path):
        exe = tmp_path / "积磊截图.exe"
        exe.write_bytes(b"OLD-VERSION")
        new = tmp_path / "积磊截图.new.exe"
        new.write_bytes(b"NEW-VERSION")
        return exe, new

    def test_replaces_exe_and_keeps_backup(self, monkeypatch, tmp_path, qapp):
        from core import updater

        exe, new = self._fake_exe(tmp_path)
        started = []
        monkeypatch.setattr(updater.sys, "executable", str(exe))
        monkeypatch.setattr(
            updater.subprocess, "Popen", lambda *args, **kwargs: started.append(args)
        )

        assert updater.install_and_restart(str(new)) is True
        assert exe.read_bytes() == b"NEW-VERSION"
        assert (tmp_path / "积磊截图.exe.old").read_bytes() == b"OLD-VERSION"
        assert started and started[0][0] == [str(exe)]

    def test_missing_download_reports_failure(self, monkeypatch, tmp_path, qapp):
        from core import updater

        exe, _ = self._fake_exe(tmp_path)
        monkeypatch.setattr(updater.sys, "executable", str(exe))

        assert updater.install_and_restart(str(tmp_path / "不存在.exe")) is False
        assert exe.read_bytes() == b"OLD-VERSION"


class TestCleanupPreviousInstall:
    def test_removes_leftovers_after_restart(self, monkeypatch, tmp_path):
        from core import updater

        exe = tmp_path / "积磊截图.exe"
        exe.write_bytes(b"NEW-VERSION")
        stale = tmp_path / "积磊截图.exe.old"
        stale.write_bytes(b"OLD-VERSION")
        leftover = tmp_path / "积磊截图.new.exe"
        leftover.write_bytes(b"NEW-VERSION")

        monkeypatch.setattr(updater.sys, "executable", str(exe))
        monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
        updater.cleanup_previous_install()

        assert not stale.exists()
        assert not leftover.exists()
        assert exe.exists()


class TestVersionComparison:
    def test_is_newer_uses_three_part_semver(self):
        from core import updater

        assert updater.is_newer("2.6.2", "2.6.1")
        assert not updater.is_newer("2.6.1", "2.6.1")
        assert not updater.is_newer("2.6.0", "2.6.1")
        assert updater.is_newer("2.7.0", "2.6.9")
