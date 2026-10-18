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
from PySide6.QtWidgets import QDialog

import ui.update_flow as update_flow
from ui.update_flow import check_for_update_interactive


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


def _fake_dialog_class(sink):
    """替换 _UpdateDialog 的假弹窗：记录"被弹出"的事实。

    必须是真 QDialog——更新流程现在走 show() + finished 信号（非模态），
    只实现 exec() 的替身接不住这套调用。
    """

    class _FakeDialog(QDialog):
        def __init__(self, parent, info):
            super().__init__(parent)
            sink.append((parent, info, QThread.currentThread()))

    return _FakeDialog


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

        monkeypatch.setattr(update_flow, "_UpdateDialog", _fake_dialog_class(shown))
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
        monkeypatch.setattr(update_flow, "_UpdateDialog", _fake_dialog_class(shown))
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


class TestUpdateDialogIsNotModal:
    """更新弹窗必须非模态。

    模态窗口会屏蔽本应用其它窗口的输入，MainApp._activate_blocking_modal 见到模态
    就**直接放弃整次截图**——表现就是"检查更新弹窗一出来，截图热键就没用了"。
    """

    def test_dialog_is_not_modal(self, qapp):
        dialog = update_flow._UpdateDialog(None, _fake_info())
        try:
            assert dialog.isModal() is False
        finally:
            dialog.deleteLater()

    def test_presenting_keeps_it_non_modal_and_reuses_the_window(
        self, monkeypatch, qapp, qtbot
    ):
        created = []
        real_dialog = update_flow._UpdateDialog

        def _factory(parent, info):
            dialog = real_dialog(parent, info)
            created.append(dialog)
            return dialog

        monkeypatch.setattr(update_flow, "_UpdateDialog", _factory)
        controller = _reset_controller(monkeypatch)

        controller._present_update(_fake_info())
        controller._present_update(_fake_info())

        assert len(created) == 1, "第二次提示不该再开一个窗口"
        assert controller.dialog is created[0]
        assert created[0].isModal() is False
        created[0].reject()
        qtbot.waitUntil(lambda: controller.dialog is None, timeout=5000)


class TestSidebarUpdateEntry:
    """侧栏底部入口是「检查更新」，点一下**直接查**（不再先进「软件信息」页），
    版本号显示在它正上方。"""

    def test_nav_entry_and_version_label(self, qapp, qtbot):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QLabel

        from main_app import APP_VERSION
        from ui.settings_ui.dialog import SettingsDialog

        dialog = SettingsDialog()
        dialog.show()
        qtbot.waitExposed(dialog)
        try:
            entry = dialog.nav_list.widget("about")
            assert entry is not None, "没有找到底部的「检查更新」导航项"
            assert entry.text() == "Check for Updates"

            labels = [
                label for label in dialog.nav_list.findChildren(QLabel)
                if APP_VERSION in label.text()
            ]
            assert labels, "侧栏没有显示版本号"
            label = labels[0]
            assert label.text().startswith("v")
            assert label.mapTo(dialog.nav_list, QPoint(0, 0)).y() < entry.mapTo(
                dialog.nav_list, QPoint(0, 0)
            ).y(), "版本号必须显示在「检查更新」上方"
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_software_information_page_is_gone(self, qapp):
        """「软件信息」整页移除：设置窗里没有它那一页，标题也没有这个词条。"""
        from ui.settings_ui.dialog import SettingsDialog

        dialog = SettingsDialog()
        try:
            assert not hasattr(dialog, "about_page"), "软件信息页不该再被创建"
            # 9 个内容页（0~8）：快捷键、截图、剪贴板、外观、翻译、日志、其他、
            # 隐藏的开发者页、账号页
            expected_pages = 10 if dialog._permissions_stack_index >= 0 else 9
            assert dialog.content_stack.count() == expected_pages
            # 底部「检查更新」不对应任何一个内容页
            assert all(
                stack_index is not None
                for _key, _icon, _text, stack_index, _pos in dialog._nav_items
                if _key != "about"
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_clicking_check_update_runs_the_check_without_switching_page(
        self, monkeypatch, qapp, qtbot
    ):
        """点底部入口：直接发起手动检查，右侧内容页不切换。"""
        from ui.settings_ui.dialog import SettingsDialog

        calls = []
        monkeypatch.setattr(
            update_flow, "check_for_update_interactive",
            lambda: calls.append(True),
        )

        dialog = SettingsDialog()
        dialog.show()
        qtbot.waitExposed(dialog)
        try:
            entry = dialog.nav_list.widget("about")
            # 先停在账号页（8），点完还该停在账号页
            dialog._on_nav_changed(8, "account")
            entry.click()

            assert calls == [True], "点击应当直接触发检查更新"
            assert dialog.content_stack.currentIndex() == 8, "检查更新不该切到任何页面"
        finally:
            dialog.close()
            dialog.deleteLater()


class TestSidebarCheckBusyState:
    """侧栏「检查更新」查询期间禁用并显示"Checking..."，查完恢复。"""

    def test_entry_busy_state_follows_controller(self, monkeypatch, qapp, qtbot):
        gate = threading.Event()

        def _slow_check():
            gate.wait(5)
            return None

        monkeypatch.setattr(update_flow.updater, "check_for_update", _slow_check)
        monkeypatch.setattr(update_flow, "show_info_dialog", lambda *a: None)
        controller = _reset_controller(monkeypatch)

        from ui.settings_ui.dialog import SettingsDialog

        dialog = SettingsDialog()
        try:
            entry = dialog.nav_list.widget("about")
            assert entry.text() == "Check for Updates"

            check_for_update_interactive()
            qtbot.waitUntil(lambda: not entry.isEnabled(), timeout=5000)
            assert entry.text() == "Checking..."

            gate.set()
            qtbot.waitUntil(lambda: entry.isEnabled(), timeout=5000)
            assert entry.text() == "Check for Updates"
        finally:
            dialog.close()
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
        from platforms import factory

        # 这是 Windows onefile 替换契约，Mac .app 后端由独立用例覆盖。
        monkeypatch.setattr(factory, "get_native_updater", lambda: None)
        monkeypatch.setattr(updater.sys, "platform", "win32")

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
