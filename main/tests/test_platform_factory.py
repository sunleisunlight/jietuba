# -*- coding: utf-8 -*-
"""平台工厂测试：get_platform_backend() 返回当前平台后端，七接口齐全。"""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="本组测试验证 macOS 平台后端（Windows 由 Windows CI 覆盖）",
)


def test_factory_returns_macos_backend():
    from platforms import get_platform_backend
    backend = get_platform_backend()
    assert backend is not None
    # macOS 后端必须提供七个平台接口
    for name in (
        "capture", "hotkeys", "clipboard", "windows",
        "accessibility", "permissions", "coordinates",
    ):
        assert hasattr(backend, name), f"缺少平台接口 {name}"


def test_backend_interfaces_exist():
    """base 抽象层七个接口均可实例化到 macOS 实现。"""
    from platforms import get_platform_backend
    backend = get_platform_backend()
    # 每个子模块都应暴露统一方法名（业务层契约）
    for method, args in [
        ("capture.capture_all_screens", ()),
        ("hotkeys.register", (None,)),
        ("clipboard.copy_image", (None,)),
        ("windows.enum_windows", ()),
        ("accessibility.scan_window", (0,)),
        ("permissions.screen_capture_status", ()),
        ("coordinates.qt_to_capture_factor", (0, 0)),
    ]:
        obj = backend
        for part in method.split("."):
            obj = getattr(obj, part)
        assert callable(obj), f"{method} 不是可调用对象"


def test_factory_cached_instance():
    from platforms import get_platform_backend
    assert get_platform_backend() is get_platform_backend()
