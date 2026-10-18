# -*- coding: utf-8 -*-
"""macOS 权限后端测试：三权限查询接口 + 打开系统设置引导。"""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="权限状态在 macOS 上验证（Windows 恒为 granted/not_applicable）",
)


def test_permission_backend_interfaces():
    """三个权限查询接口返回 PermissionStatus 枚举成员。"""
    from platforms import get_platform_backend
    from platforms.base.permissions import PermissionStatus

    perm = get_platform_backend().permissions
    for query in (
        perm.screen_capture_status,
        perm.accessibility_status,
        perm.input_monitoring_status,
    ):
        status = query()
        assert isinstance(status, PermissionStatus), f"{query} 返回 {status!r}"


def test_permission_status_values():
    from platforms.base.permissions import PermissionStatus
    assert {s.value for s in PermissionStatus} >= {
        "granted", "denied", "not_requested", "unknown", "not_applicable",
    }


def test_request_accessibility_no_crash(monkeypatch):
    """测试不弹真实系统授权框，也不改变本机权限。"""
    from platforms.macos import permissions
    monkeypatch.setattr(permissions, "_ax_is_trusted_with_options", lambda: False)
    monkeypatch.setattr(permissions, "_ax_is_trusted", lambda: False)
    from platforms import get_platform_backend
    perm = get_platform_backend().permissions
    try:
        perm.request_accessibility()
    except Exception as e:  # 不允许向上抛（权限对话框被系统拦截等）
        pytest.fail(f"request_accessibility 抛异常: {e}")


@pytest.mark.parametrize("granted", [True, False])
def test_input_monitoring_uses_read_only_preflight(monkeypatch, granted):
    import Quartz
    from platforms.macos.permissions import MacOSPermissionBackend
    from platforms.base.permissions import PermissionStatus
    monkeypatch.setattr(Quartz, "CGPreflightListenEventAccess", lambda: granted)
    monkeypatch.setattr(Quartz, "CGEventTapCreate", lambda *a: pytest.fail("must not create tap"))
    expected = PermissionStatus.GRANTED if granted else PermissionStatus.DENIED
    assert MacOSPermissionBackend().input_monitoring_status() == expected


def test_open_system_settings_routes():
    """open_system_settings 对三类权限均生成合法 pane 并成功 open。"""
    from platforms import get_platform_backend
    perm = get_platform_backend().permissions
    import subprocess
    original = subprocess.Popen
    calls = []
    try:
        subprocess.Popen = lambda cmd, **kw: calls.append(cmd) or original(["true"])
        perm.open_system_settings("screen_capture")
        perm.open_system_settings("accessibility")
        perm.open_system_settings("input_monitoring")
    finally:
        subprocess.Popen = original
    assert len(calls) == 3
    for cmd in calls:
        assert cmd[0] == "open"
        assert "x-apple.systempreferences:" in cmd[1]


def test_denial_and_api_failure_are_distinguished(monkeypatch):
    from platforms.macos import permissions
    from platforms.base.permissions import PermissionStatus
    backend = permissions.MacOSPermissionBackend()
    monkeypatch.setattr(permissions, "_cg_preflight", lambda: False)
    monkeypatch.setattr(permissions, "_ax_is_trusted", lambda: False)
    assert backend.screen_capture_status() == PermissionStatus.DENIED
    assert backend.accessibility_status() == PermissionStatus.DENIED

    def failed():
        raise RuntimeError("synthetic native API failure")

    monkeypatch.setattr(permissions, "_cg_preflight", failed)
    monkeypatch.setattr(permissions, "_ax_is_trusted", failed)
    assert backend.screen_capture_status() == PermissionStatus.UNKNOWN
    assert backend.accessibility_status() == PermissionStatus.UNKNOWN


def test_permission_request_can_recover(monkeypatch):
    from platforms.macos import permissions
    from platforms.base.permissions import PermissionStatus
    state = {"allowed": False}
    monkeypatch.setattr(permissions, "_cg_preflight", lambda: state["allowed"])
    monkeypatch.setattr(permissions, "_cg_request", lambda: state.update(allowed=True))
    backend = permissions.MacOSPermissionBackend()
    assert backend.screen_capture_status() == PermissionStatus.DENIED
    assert backend.request_screen_capture()
    assert backend.screen_capture_status() == PermissionStatus.GRANTED
