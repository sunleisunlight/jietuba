# -*- coding: utf-8 -*-
"""主剪贴板窗口的鼠标拖拽排序。

「全部历史」原视图（DESC）与自建分组视图（ASC）都允许拖拽：两种视图里视觉上方
邻居都是 before_id、下方邻居是 after_id，底层 move_item_between 按条目所在
group_id 自选排序方向。内置类型分组（"text"/"image"）/ 搜索 / 类型 / 时间筛选
是过滤出来的局部视图，落库会把不可见条目搞乱，仍然禁用。
分组视图同样按 is_pinned DESC 分区置顶，跨置顶区拖拽在 Python 层拒绝。
"""

from datetime import datetime

import pytest

from clipboard.controllers.clipboard_controller import ClipboardController
from clipboard.core.models import ClipboardItem


class _FakeManager:
    def __init__(self, result: bool = True, pinned: dict = None):
        self._result = result
        self.calls = []
        self._pinned = pinned or {}

    def move_item_between(self, item_id, before_id=None, after_id=None):
        self.calls.append((item_id, before_id, after_id))
        return self._result

    def get_item(self, item_id):
        if item_id not in self._pinned:
            return None
        return ClipboardItem(
            id=item_id, content="x", content_type="text",
            is_pinned=self._pinned[item_id],
        )


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    ctrl = ClipboardController(_FakeManager())
    ctrl.load_history = lambda: None
    return ctrl


def test_default_history_view_is_reorderable(controller):
    assert controller.current_group_id is None
    assert controller.can_reorder_current_view() is True


def test_custom_group_view_is_reorderable(controller):
    controller.current_group_id = 7
    assert controller.can_reorder_current_view() is True


@pytest.mark.parametrize("group_id", ["text", "image"])
def test_builtin_group_views_are_not_reorderable(controller, group_id):
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


def test_custom_group_with_search_is_not_reorderable(controller):
    controller.current_group_id = 7
    assert controller.can_reorder_current_view() is True
    controller._search_text = "关键词"
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


def test_group_view_reorder_uses_visual_neighbors(monkeypatch):
    """分组 ASC 视图：视觉上邻仍是 before_id、下邻仍是 after_id。"""
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    ctrl = ClipboardController(_FakeManager())
    reloads = []
    ctrl.load_history = lambda: reloads.append(1)
    ctrl.current_group_id = 7

    assert ctrl.reorder_history_item(3, before_id=2, after_id=4) is True
    assert ctrl.manager.calls == [(3, 2, 4)]
    assert reloads == [1]


def test_group_view_reorder_blocked_across_pin_partition(monkeypatch):
    """分组内非置顶条目不能拖进置顶区（邻居与被拖项置顶状态不同即拒绝）。"""
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    # 被拖项 3 非置顶；上邻 5 置顶 → 跨区
    manager = _FakeManager(pinned={3: False, 5: True, 4: False})
    ctrl = ClipboardController(manager)
    ctrl.load_history = lambda: None
    ctrl.current_group_id = 7

    assert ctrl.reorder_history_item(3, before_id=5, after_id=4) is False
    assert manager.calls == []

    # 同一分区（都非置顶）放行
    manager2 = _FakeManager(pinned={3: False, 5: False, 4: False})
    ctrl2 = ClipboardController(manager2)
    ctrl2.load_history = lambda: None
    ctrl2.current_group_id = 7
    assert ctrl2.reorder_history_item(3, before_id=5, after_id=4) is True
    assert manager2.calls == [(3, 5, 4)]


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
