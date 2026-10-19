"""macOS native calls are faked; these wiring contracts run on both OSes."""
from types import SimpleNamespace

import pytest

from platforms.macos import clipboard


@pytest.fixture(autouse=True)
def trusted_input(monkeypatch):
    monkeypatch.setattr(clipboard, "_ax_is_trusted", lambda: True)


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


def test_untrusted_input_does_not_inject(monkeypatch):
    monkeypatch.setattr(clipboard, "_ax_is_trusted", lambda: False)
    monkeypatch.setattr(clipboard, "_post_key_event", lambda *a, **kw: pytest.fail("no permission"))
    assert not clipboard.send_cmd_v()


@pytest.mark.parametrize("matches", [True, False])
def test_same_process_other_window_is_not_a_valid_target(monkeypatch, matches):
    import platforms
    from platforms.macos.window import MacPasteTarget
    target = MacPasteTarget(42, object())
    sent, notices = [], []
    monkeypatch.setattr(platforms, "get_platform_backend", lambda: SimpleNamespace(
        windows=SimpleNamespace(get_foreground_handle=lambda: 42,
                                current_pid=lambda: 1, is_alive=lambda pid: True,
                                matches_paste_target=lambda value: value is target and matches)))
    monkeypatch.setattr(clipboard, "_send_paste", lambda: sent.append(True))
    monkeypatch.setattr(clipboard, "_notify_paste_failure", lambda: notices.append(True))
    clipboard.MacOSClipboardBackend().paste_to_target(target)
    assert sent == ([True] if matches else [])
    assert notices == ([] if matches else [True])


def test_tracker_captures_native_window_identity(monkeypatch):
    import platforms
    from clipboard.controllers import foreground_tracker as tracker
    from platforms.macos import window
    backend = window.MacOSWindowBackend()
    marker = object()
    monkeypatch.setattr(tracker, "_IS_MACOS", True)
    monkeypatch.setattr(platforms, "get_platform_backend", lambda: SimpleNamespace(windows=backend))
    monkeypatch.setattr(backend, "get_foreground_handle", lambda: 42)
    monkeypatch.setattr(backend, "current_pid", lambda: 1)
    monkeypatch.setattr(window, "_focused_window", lambda pid: marker)
    target = tracker.get_foreground_hwnd()
    assert int(target) == 42
    assert target.window is marker


def test_tracker_refreshes_identity_when_pid_is_unchanged(monkeypatch):
    from clipboard.controllers.foreground_tracker import ForegroundWindowTracker
    from platforms.macos.window import MacPasteTarget
    tracker = ForegroundWindowTracker()
    old, new = MacPasteTarget(42, object()), MacPasteTarget(42, object())
    tracker._target_hwnd = old
    monkeypatch.setattr(tracker, "_read_candidate", lambda: new)
    assert not tracker.sample()
    assert tracker._target_hwnd is new


def test_activation_timeout_never_pastes_into_another_app(monkeypatch):
    import platforms
    monkeypatch.setattr(platforms, "get_platform_backend", lambda: SimpleNamespace(
        windows=SimpleNamespace(get_foreground_handle=lambda: 99,
                                current_pid=lambda: 1, is_alive=lambda pid: True),
    ))
    monkeypatch.setattr(clipboard, "_send_paste", lambda: pytest.fail("wrong app"))
    monkeypatch.setattr(clipboard, "_notify_paste_failure", lambda: None)
    clipboard._activate_then_paste(42, clipboard._ACTIVATE_MAX_ATTEMPTS)


def test_macos_display_matches_registered_modifier(monkeypatch):
    from core import shortcut_manager
    from platforms.macos.hotkey import MacOSHotkeyBackend, cmdKey, controlKey

    monkeypatch.setattr(shortcut_manager.sys, "platform", "darwin")
    assert shortcut_manager.display_hotkey_str("ctrl+shift+a") == "Command+Shift+a"
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
