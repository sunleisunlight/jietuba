# -*- coding: utf-8 -*-
"""macOS 全局热键自检：系统丢掉 Carbon 注册后必须能自动补回来。"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Carbon 热键注册只在 macOS 生效"
)


def test_ensure_registered_rebuilds_a_dropped_hotkey():
    from platforms.macos.hotkey import MacOSHotkeyBackend

    backend = MacOSHotkeyBackend()
    try:
        assert backend.register(1, "ctrl+shift+f19", lambda: None)

        # 注册还在时自检不应该重复注册
        assert backend.ensure_registered() == 0

        # 模拟系统悄悄丢掉注册：直接向 OS 注销，但保留 Python 侧登记表
        backend._framework.UnregisterEventHotKey(backend._id_to_ref[1])

        assert backend.ensure_registered() == 1
        assert 1 in backend._id_to_ref
        assert 1 in backend._id_to_callback
        # 补回来之后应该稳定
        assert backend.ensure_registered() == 0
    finally:
        backend.unregister_all()
