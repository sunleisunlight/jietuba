# -*- coding: utf-8 -*-
"""macOS 标题栏：红黄绿交给 AppKit 原生按钮，不再自绘一组和它重叠。"""

import sys

import pytest
from PySide6.QtWidgets import QWidget

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="交通灯按钮只在 macOS 生效"
)


def test_windows_caption_buttons_are_removed_on_macos(qapp):
    from ui.fluent_lite.titlebar import FluentTitleBar

    window = QWidget()
    window.setWindowTitle("积磊截图")
    bar = FluentTitleBar(window)

    layout = bar.hBoxLayout
    # 三个 Windows 风格按钮必须彻底退出布局，否则右上角还会留一个 ×
    for button in (bar.minBtn, bar.maxBtn, bar.closeBtn):
        assert layout.indexOf(button) == -1
    # 左上角给原生红绿灯留出空位，标题文字不会压在按钮下面
    assert bar.trafficSpacer.width() > 0
    assert layout.indexOf(bar.trafficSpacer) < layout.indexOf(bar.titleLabel)
    # 不能再自绘一组红绿灯：窗口显示后 AppKit 的原生按钮会出现，
    # 两套叠在一起就是用户截图里"两个叠在一起了"的红黄绿。
    assert not hasattr(bar, "trafficLights")
