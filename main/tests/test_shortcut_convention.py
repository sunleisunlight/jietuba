"""Actual Qt editors plus both native key conventions; no system registrations."""
import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit
from platforms.base.shortcut import ShortcutConvention


@pytest.mark.parametrize("macos", [True, False])
def test_localized_placeholder_preserves_prose(qapp, monkeypatch, macos):
    from ui import hotkey_edit
    policy = ShortcutConvention(macos=macos)
    monkeypatch.setattr(hotkey_edit, "get_shortcut_convention", lambda: policy)
    widget = hotkey_edit.HotkeyEdit()
    widget.setPlaceholderText("例如: ctrl+shift+a")
    assert widget.edit.placeholderText() == ("例如: Command+Shift+a" if macos
                                            else "例如: ctrl+shift+a")
    widget.deleteLater()


@pytest.mark.parametrize("macos", [True, False])
@pytest.mark.parametrize("modifier,token", [(Qt.ControlModifier, "ctrl"),
                                          (Qt.AltModifier, "alt"),
                                          (Qt.MetaModifier, "meta")])
def test_editors_capture_display_and_store(qapp, monkeypatch, macos, modifier, token):
    from ui import hotkey_edit, inapp_key_edit
    policy = ShortcutConvention(macos=macos)
    expected = ("lctrl" if macos else "win") if token == "meta" else token
    for module, editor_type in [(hotkey_edit, hotkey_edit._HotkeyLineEdit),
                                (inapp_key_edit, inapp_key_edit.InAppKeyEdit)]:
        monkeypatch.setattr(module, "get_shortcut_convention", lambda: policy)
        widget = editor_type()
        widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_A, modifier))
        assert widget.text() == expected + "+a"
        assert QLineEdit.text(widget) == policy.display(expected + "+a")
        widget.setText("ctrl+shift+a")
        assert widget.text() == "ctrl+shift+a"
        assert QLineEdit.text(widget) == ("Command+Shift+a" if macos else "ctrl+shift+a")
        widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier))
        assert widget.text() == "ctrl+"
        assert QLineEdit.text(widget).endswith("+")
        widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Control, Qt.NoModifier))
        assert widget.text() == ""
        widget.deleteLater()


def test_mac_aliases_match_native_and_qt(monkeypatch):
    from core import shortcut_manager as sm
    from platforms.macos.hotkey import MacOSHotkeyBackend, cmdKey, controlKey
    policy = ShortcutConvention(macos=True)
    monkeypatch.setattr("platforms.factory.get_shortcut_convention", lambda: policy)
    for token in ("ctrl", "cmd", "command", "win", "meta", "super"):
        assert sm.parse_shortcut_to_qt(token + "+a") == (Qt.Key_A, Qt.ControlModifier)
        assert MacOSHotkeyBackend.parse_hotkey(token + "+a")[1] == cmdKey
    for token in ("lctrl", "control"):
        assert sm.parse_shortcut_to_qt(token + "+a") == (Qt.Key_A, Qt.MetaModifier)
        assert MacOSHotkeyBackend.parse_hotkey(token + "+a")[1] == controlKey


@pytest.mark.parametrize("target,alive", [(None, True), (42, False), (1, True)])
def test_invalid_paste_target_is_never_replaced_by_current_app(monkeypatch, target, alive):
    from types import SimpleNamespace
    from platforms.macos import clipboard
    notices = []
    monkeypatch.setattr("platforms.get_platform_backend", lambda: SimpleNamespace(
        windows=SimpleNamespace(current_pid=lambda: 1, is_alive=lambda pid: alive)))
    monkeypatch.setattr(clipboard, "_send_paste", lambda: pytest.fail("unsafe paste"))
    monkeypatch.setattr(clipboard, "_notify_paste_failure", lambda: notices.append(True))
    clipboard.MacOSClipboardBackend().paste_to_target(target)
    assert notices == [True]
