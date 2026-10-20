"""AX window targeting/Retina mapping, no permission requests or real data."""
import sys
from types import SimpleNamespace
from platforms.macos import accessibility as ax


def test_scan_targets_only_requested_window(monkeypatch):
    monkeypatch.setitem(sys.modules, "ApplicationServices", SimpleNamespace(
        AXUIElementCreateApplication=lambda pid: "app", kAXWindowsAttribute="windows"))
    monkeypatch.setattr(ax, "_pid_for_window", lambda wid: 123)
    monkeypatch.setattr(ax, "_window_frame", lambda wid: (20, 30, 400, 300))
    monkeypatch.setattr(ax, "_ax_value", lambda *a: ["other", "target"])
    monkeypatch.setattr(ax, "_ax_position_size", lambda win: (20, 30, 400, 300) if win == "target" else (0, 0, 200, 100))
    scanned, done = [], []
    monkeypatch.setattr(ax, "_scan_tree", lambda win, *a: scanned.append(win))
    ax._MacScanWorker(42, lambda *args: done.append(args)).run()
    assert scanned == ["target"]
    assert done == [(42, ())]


def test_ax_rect_uses_capture_pixels(monkeypatch):
    monkeypatch.setitem(sys.modules, "ApplicationServices", SimpleNamespace(
        kAXChildrenAttribute="children", kAXRoleAttribute="role", kAXWindowRole="window"))
    monkeypatch.setattr(ax, "_ax_value", lambda node, attr: ["button"] if node == "root" and attr == "children" else ([] if attr == "children" else "button"))
    monkeypatch.setattr(ax, "_ax_position_size", lambda node: (-300, 10, 100, 50))
    monkeypatch.setattr(ax.MacOSCoordinateMapper, "reference_factor", lambda self: 2)
    out = []
    ax._scan_tree("root", out, 0, 12, 4096)
    assert [item.rect for item in out] == [(-600, 20, -400, 120)]
