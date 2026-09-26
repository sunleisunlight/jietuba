"""macOS native calls are faked; these wiring contracts run on both OSes."""
from types import SimpleNamespace

import pytest

from platforms.macos import clipboard


@pytest.mark.parametrize("action,key", [(clipboard.send_cmd_v, 9), (clipboard.send_copy_shortcut, 8)])
def test_command_shortcut_emits_correct_key_and_releases(monkeypatch, action, key):
    events = []
    monkeypatch.setattr(clipboard, "_post_key_event", lambda key, down, **kw: events.append((key, down, kw)))
    assert action()
    assert events == [
        (0x37, True, {"command": True}),
        (key, True, {"command": True}),
        (key, False, {"command": True}),
        (0x37, False, {}),
    ]


def test_failed_key_down_still_releases_command(monkeypatch):
    events = []

    def post(key, down, **kw):
        events.append((key, down))
        if key == 9 and down:
            raise RuntimeError("injection failed")

    monkeypatch.setattr(clipboard, "_post_key_event", post)
    assert not clipboard.send_cmd_v()
    assert events[-2:] == [(9, False), (0x37, False)]


def test_backend_exposes_controller_entrypoints(monkeypatch):
    import platforms

    calls = []
    monkeypatch.setattr(platforms, "get_platform_backend", lambda: SimpleNamespace(
        windows=SimpleNamespace(set_foreground=lambda pid: calls.append(pid) or True),
    ))
    monkeypatch.setattr(clipboard, "send_cmd_v", lambda: True)
    backend = clipboard.MacOSClipboardBackend()
    assert backend.activate_target(42)
    assert calls == [42]
    assert backend.send_cmd_v()


def test_macos_display_matches_registered_modifier(monkeypatch):
    from core import shortcut_manager
    from platforms.macos.hotkey import MacOSHotkeyBackend, cmdKey, controlKey

    monkeypatch.setattr(shortcut_manager.sys, "platform", "darwin")
    assert shortcut_manager.display_hotkey_str("ctrl+shift+a") == "Cmd+Shift+a"
    assert shortcut_manager.display_hotkey_str("lctrl+a") == "Control+a"
    assert MacOSHotkeyBackend.parse_hotkey("ctrl+a")[1] == cmdKey
    assert MacOSHotkeyBackend.parse_hotkey("lctrl+a")[1] == controlKey


def test_macos_display_aliases_round_trip_in_both_parsers(monkeypatch):
    from core import shortcut_manager
    from platforms.macos.hotkey import MacOSHotkeyBackend

    monkeypatch.setattr(shortcut_manager, "_IS_MACOS", True)
    monkeypatch.setattr(shortcut_manager.sys, "platform", "darwin")
    for stored in ("ctrl+shift+a", "alt+a", "lctrl+a"):
        displayed = shortcut_manager.display_hotkey_str(stored)
        assert MacOSHotkeyBackend.parse_hotkey(displayed) == MacOSHotkeyBackend.parse_hotkey(stored)
        assert shortcut_manager.parse_shortcut_to_qt(displayed) == shortcut_manager.parse_shortcut_to_qt(stored)
        assert shortcut_manager.hotkey_identity(displayed) == shortcut_manager.hotkey_identity(stored)
