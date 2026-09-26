"""Windows backend must retain the mature window and multi-monitor implementation."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 backend import")


def test_window_queries_delegate_to_mature_finder(monkeypatch):
    from capture import window_finder
    from platforms.windows.window import WindowsWindowBackend

    calls = []
    windows = [(2**40, [-100, 0, 0, 100], "secondary")]

    class Finder:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.windows = windows

        def find_windows(self):
            calls.append("enumerate")

        def find_monitor_rect_at_point(self, x, y):
            calls.append((x, y))
            return [-1920, 0, 0, 1080]

    monkeypatch.setattr(window_finder, "WindowFinder", Finder)
    backend = WindowsWindowBackend()
    assert backend.enum_windows(offset_x=-1920, offset_y=10) is windows
    assert backend.find_monitor_rect_at_point(-100, 20) == [-1920, 0, 0, 1080]
    assert calls == [
        {"screen_offset_x": -1920, "screen_offset_y": 10}, "enumerate", {}, (-100, 20),
    ]
