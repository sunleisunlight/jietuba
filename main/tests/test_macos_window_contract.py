"""Mock 原生桥接，Windows CI 也验证 Mac 接线。"""
import sys
from types import SimpleNamespace

from platforms.macos import window


def test_display_list_uses_pyobjc_error_displays_count(monkeypatch):
    monkeypatch.setattr(window.MacOSCoordinateMapper, "reference_factor", lambda self: 1.0)
    bounds = SimpleNamespace(origin=SimpleNamespace(x=-1920, y=0),
                             size=SimpleNamespace(width=1920, height=1080))
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        kCGErrorSuccess=0, CGGetActiveDisplayList=lambda *a: (0, [7], 1),
        CGDisplayBounds=lambda display: bounds,
    ))
    assert window.MacOSWindowBackend().find_monitor_rect_at_point(-100, 30) == [-1920, 0, 0, 1080]


def test_click_through_reaches_nswindow(monkeypatch):
    native, qt = [], []
    monkeypatch.setattr(window, "_native_window", lambda widget: SimpleNamespace(
        setIgnoresMouseEvents_=native.append))
    widget = SimpleNamespace(setAttribute=lambda attr, enabled: qt.append(enabled))
    backend = window.MacOSWindowBackend()
    backend.set_window_click_through(widget, True)
    backend.set_window_click_through(widget, False)
    assert native == qt == [True, False]


def test_retina_window_rect_and_self_exclusion(monkeypatch):
    monkeypatch.setattr(window.MacOSCoordinateMapper, "reference_factor", lambda self: 2.0)
    sample = dict(kCGWindowLayer=0, kCGWindowOwnerName="Synthetic",
                  kCGWindowName="Task3", kCGWindowIsOnscreen=True,
                  kCGWindowBounds=dict(X=-500, Y=20, Width=300, Height=200),
                  kCGWindowNumber=42, kCGWindowOwnerPID=999999)
    monkeypatch.setattr(window, "_window_list", lambda: [sample, dict(sample, kCGWindowOwnerPID=window.os.getpid())])
    assert window.MacOSWindowBackend().enum_windows() == [(42, [-1000, 40, -400, 440], "Task3")]
