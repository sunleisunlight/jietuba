# -*- coding: utf-8 -*-
"""默认历史视图的鼠标拖拽排序（主剪贴板窗口）。

只有「全部历史」原视图允许拖拽：自建分组走 ASC 排序（管理窗口里拖），内置类型
分组 / 搜索 / 类型 / 时间筛选都是过滤出来的局部视图，落库会把不可见条目搞乱。
DESC 视图里视觉上方邻居就是 before_id、下方邻居是 after_id，与分组视图相反，
这里专门钉住这个传参方向，防止以后有人按 ASC 直觉写反。
"""

from datetime import datetime

import pytest

from clipboard.controllers.clipboard_controller import ClipboardController


class _FakeManager:
    def __init__(self, result: bool = True):
        self._result = result
        self.calls = []

    def move_item_between(self, item_id, before_id=None, after_id=None):
        self.calls.append((item_id, before_id, after_id))
        return self._result


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    ctrl = ClipboardController(_FakeManager())
    ctrl.load_history = lambda: None
    return ctrl


def test_default_history_view_is_reorderable(controller):
    assert controller.current_group_id is None
    assert controller.can_reorder_current_view() is True


@pytest.mark.parametrize("group_id", [7, "text", "image"])
def test_group_and_builtin_views_are_not_reorderable(controller, group_id):
    controller.current_group_id = group_id
    assert controller.can_reorder_current_view() is False


def test_filtered_views_are_not_reorderable(controller):
    controller._search_text = "关键词"
    assert controller.can_reorder_current_view() is False

    controller._search_text = None
    controller._content_type = "image"
    assert controller.can_reorder_current_view() is False

    controller._content_type = None
    controller._time_range = (datetime(2026, 1, 1), datetime(2026, 1, 2))
    assert controller.can_reorder_current_view() is False


def test_reorder_passes_visual_neighbors_in_desc_order(controller):
    reloads = []
    controller.load_history = lambda: reloads.append(1)

    # 把 id=3 拖到 id=5（视觉上方）与 id=4（视觉下方）之间
    assert controller.reorder_history_item(3, before_id=5, after_id=4) is True

    assert controller.manager.calls == [(3, 5, 4)]
    assert reloads == [1]


def test_reorder_to_very_top_uses_none_before(controller):
    assert controller.reorder_history_item(9, before_id=None, after_id=5) is True
    assert controller.manager.calls == [(9, None, 5)]


def test_reorder_to_very_bottom_uses_none_after(controller):
    assert controller.reorder_history_item(9, before_id=2, after_id=None) is True
    assert controller.manager.calls == [(9, 2, None)]


def test_backend_failure_returns_false_and_skips_reload(monkeypatch):
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    ctrl = ClipboardController(_FakeManager(result=False))
    reloads = []
    ctrl.load_history = lambda: reloads.append(1)

    assert ctrl.reorder_history_item(1, before_id=None, after_id=2) is False
    assert reloads == []


def test_reorder_blocked_in_filtered_view_does_not_touch_backend(controller):
    controller._search_text = "x"
    assert controller.reorder_history_item(1, before_id=None, after_id=2) is False
    assert controller.manager.calls == []
