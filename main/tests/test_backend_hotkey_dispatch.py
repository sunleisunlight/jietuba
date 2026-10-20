"""后端回调共享禁用/优先级链，不注册真实系统热键。"""
from types import SimpleNamespace

from core.shortcut_manager import ShortcutManager


def test_backend_hotkey_honors_suppression_and_priority(qapp):
    manager = ShortcutManager()
    registered = {}
    calls = []
    manager._hotkey_backend = SimpleNamespace(
        register=lambda hid, key, cb: registered.setdefault(hid, cb) is cb,
        unregister_all=lambda: None,
    )
    assert manager.register_hotkey("ctrl+1", lambda: calls.append("callback"))
    trigger = next(iter(registered.values()))
    manager.set_global_hotkeys_suppressed(True)
    trigger()
    assert calls == []
    manager.set_global_hotkeys_suppressed(False)
    handler = SimpleNamespace(is_active=lambda: True, handle_hotkey=lambda *a: True,
                              handler_name="test")
    manager._handlers = [handler]
    trigger()
    assert calls == []
    manager._handlers = []
    trigger()
    assert calls == ["callback"]
    manager._id_to_callback.clear()
    trigger()
    assert calls == ["callback"]
