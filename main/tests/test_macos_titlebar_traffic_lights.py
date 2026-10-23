# -*- coding: utf-8 -*-
"""macOS 标题栏：左上角红黄绿交通灯替代右上角 Windows 的 × − □。"""

import sys

import pytest
from PySide6.QtWidgets import QWidget

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="交通灯按钮只在 macOS 生效"
)


def test_caption_buttons_are_replaced_by_traffic_lights(qapp):
    from ui.fluent_lite.titlebar import FluentTitleBar, _MacTrafficLights

    window = QWidget()
    window.setWindowTitle("积磊截图")
    bar = FluentTitleBar(window)

    assert isinstance(bar.trafficLights, _MacTrafficLights)
    layout = bar.hBoxLayout
    # 三个 Windows 风格按钮必须彻底退出布局，否则右上角还会留一个 ×
    for button in (bar.minBtn, bar.maxBtn, bar.closeBtn):
        assert layout.indexOf(button) == -1
    # 交通灯排在标题文字之前，标题不会被压在按钮下面
    assert layout.indexOf(bar.trafficLights) < layout.indexOf(bar.titleLabel)


def test_traffic_light_hit_testing_matches_the_three_circles(qapp):
    from ui.fluent_lite.titlebar import _MacTrafficLights

    lights = _MacTrafficLights()
    for index in range(3):
        center = lights._circle_rect(index).center()
        assert lights._index_at(center.x()) == index
    assert lights._index_at(-5) == -1
    assert lights._index_at(lights.width() + 5) == -1
