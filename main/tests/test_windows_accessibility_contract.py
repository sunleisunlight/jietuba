"""Verify the Windows adapter wiring with a fake COM provider on both platforms."""
from types import SimpleNamespace

import pytest

from platforms.windows.accessibility import WindowsAccessibilityBackend


def test_scan_uses_existing_provider_and_closes_on_same_thread(monkeypatch):
    from capture import uia_element_finder as uia
    import threading

    calls = []

    class Provider:
        def __init__(self):
            calls.append(("create", threading.get_ident()))

        def scan(self, handle):
            calls.append((handle, threading.get_ident()))
            return (
                SimpleNamespace(rect=(0, 0, 100, 100), order=1),
                SimpleNamespace(rect=(5, 5, 10, 10), order=2),
                SimpleNamespace(rect=(0, 0, 1, 1), order=3),
            )

        def close(self):
            calls.append(("close", threading.get_ident()))

    monkeypatch.setattr(uia, "is_uia_available", lambda: True)
    monkeypatch.setattr(uia, "_UIABackend", Provider)
    result = WindowsAccessibilityBackend().scan_window(123, max_elements=2)
    assert [s.order for s in result] == [2, 1]
    assert [c[0] for c in calls] == ["create", 123, "close"]
    assert len({c[1] for c in calls}) == 1


def test_scan_errors_are_visible_and_provider_is_closed(monkeypatch):
    from capture import uia_element_finder as uia

    closed = []

    class Provider:
        def scan(self, handle):
            raise RuntimeError("provider failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(uia, "is_uia_available", lambda: True)
    monkeypatch.setattr(uia, "_UIABackend", Provider)
    with pytest.raises(RuntimeError, match="provider failed"):
        WindowsAccessibilityBackend().scan_window(123)
    assert closed == [True]


def test_hung_check_uses_existing_function(monkeypatch):
    from capture import uia_element_finder as uia

    monkeypatch.setattr(uia, "is_hung_window", lambda handle: handle == 123)
    backend = WindowsAccessibilityBackend()
    assert backend.is_handle_hung(123)
    assert not backend.is_handle_hung(456)
