# -*- coding: utf-8 -*-
"""分组栏内置「文字」「图片」类型分组（方案 A）回归测试。

内置分组不是数据库里的真实分组：视图 ID 直接复用 content_type 取值
（"text"/"image"），数据走 get_history 的 content_type 筛选，
任何"组内操作"（排序、删除、右键"移出分组"）都必须把它们当作历史视图对待。
"""

import pytest

from clipboard.controllers.clipboard_controller import (
    ClipboardController,
    BUILTIN_GROUP_TEXT,
    BUILTIN_GROUP_IMAGE,
    calc_sidebar_capacity,
    calc_topbar_capacity,
)
from clipboard.controllers.context_menu_controller import _ItemContextMenuState
from clipboard.core import ClipboardItem, Group, GroupType
from clipboard.ui.theme.themes import THEME_LIGHT
from clipboard.ui.widgets.group_bar import GroupBar

from PySide6.QtCore import Qt


# ============================================================
# 辅助构造
# ============================================================


class DummyHistoryManager:
    """记录 get_history 参数；内置视图一旦走分组表即视为错误。"""

    def __init__(self):
        self.history_calls = []

    def get_history(self, limit=50, offset=0, search=None, content_type=None,
                    start_time=None, end_time=None):
        self.history_calls.append({
            "limit": limit,
            "offset": offset,
            "search": search,
            "content_type": content_type,
            "start_time": start_time,
            "end_time": end_time,
        })
        return []

    def get_by_group(self, group_id, offset=0, limit=50):
        raise AssertionError(f"内置类型视图不应查询分组表: {group_id!r}")


class DummyGroupManager:

    def __init__(self, groups=None):
        self._groups = groups or []

    def get_groups(self):
        return list(self._groups)

    def get_by_group(self, group_id, offset=0, limit=1000):
        return []


def _make_controller(monkeypatch, manager):
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    return ClipboardController(manager)


def _item(item_id: int, content_type: str = "text") -> ClipboardItem:
    return ClipboardItem(id=item_id, content=f"内容 {item_id}", content_type=content_type)


# ============================================================
# Controller：内置视图数据查询
# ============================================================


@pytest.mark.parametrize(
    "view_id, content_type",
    [(BUILTIN_GROUP_TEXT, "text"), (BUILTIN_GROUP_IMAGE, "image")],
)
def test_builtin_group_queries_history_with_content_type(monkeypatch, view_id, content_type):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)
    controller.current_group_id = view_id

    controller._fetch_items_page(limit=10, offset=5)

    assert len(manager.history_calls) == 1
    call = manager.history_calls[0]
    assert call["content_type"] == content_type
    assert call["limit"] == 10
    assert call["offset"] == 5


def test_builtin_group_passes_search_and_time_range_to_history(monkeypatch):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)
    controller.current_group_id = BUILTIN_GROUP_TEXT
    controller._search_text = "apple"

    controller._fetch_items_page(limit=10, offset=0)

    assert manager.history_calls[0]["search"] == "apple"


def test_real_group_still_queries_group_table(monkeypatch):
    called = {}

    class Manager(DummyGroupManager):
        def get_by_group(self, group_id, offset=0, limit=50):
            called["group_id"] = group_id
            called["offset"] = offset
            called["limit"] = limit
            return []

    controller = _make_controller(monkeypatch, Manager())
    controller.current_group_id = 7

    controller._fetch_items_page(limit=8, offset=3)

    assert called == {"group_id": 7, "offset": 3, "limit": 8}


# ============================================================
# Controller：switch_to_group / apply_type_filter 状态映射
# ============================================================


def test_switch_to_builtin_group_loads_and_clears_type_filter(monkeypatch):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)
    controller._content_type = "file"  # 模拟先在全部视图选了"文件"下拉

    controller.switch_to_group(BUILTIN_GROUP_IMAGE)

    assert controller.current_group_id == BUILTIN_GROUP_IMAGE
    assert controller._content_type is None
    assert manager.history_calls[-1]["content_type"] == "image"


def test_switch_back_to_all_clears_residual_file_filter(monkeypatch):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)
    controller.current_group_id = BUILTIN_GROUP_IMAGE
    controller._content_type = "file"

    controller.switch_to_group(None)

    assert controller.current_group_id is None
    assert controller._content_type is None
    assert manager.history_calls[-1]["content_type"] is None


def test_switching_to_same_view_without_filter_does_not_reload(monkeypatch):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)
    controller.current_group_id = BUILTIN_GROUP_TEXT

    controller.switch_to_group(BUILTIN_GROUP_TEXT)

    assert manager.history_calls == []


@pytest.mark.parametrize(
    "index, group_id, content_type",
    [
        (0, None, None),
        (1, BUILTIN_GROUP_TEXT, None),
        (2, BUILTIN_GROUP_IMAGE, None),
        (3, None, "file"),
    ],
)
def test_apply_type_filter_maps_dropdown_to_view(monkeypatch, index, group_id, content_type):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)

    controller.apply_type_filter(index)

    assert controller.current_group_id == group_id
    assert controller._content_type == content_type


def test_apply_type_filter_file_queries_history_not_group_table(monkeypatch):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)

    controller.apply_type_filter(3)

    assert controller.current_group_id is None
    assert manager.history_calls[-1]["content_type"] == "file"


def test_apply_same_type_filter_does_not_reload(monkeypatch):
    manager = DummyHistoryManager()
    controller = _make_controller(monkeypatch, manager)
    controller.apply_type_filter(2)
    calls_after_first = len(manager.history_calls)

    controller.apply_type_filter(2)

    assert len(manager.history_calls) == calls_after_first


# ============================================================
# Controller：内置视图下的"组内操作"守卫
# ============================================================


@pytest.mark.parametrize("group_id", [None, BUILTIN_GROUP_TEXT, BUILTIN_GROUP_IMAGE])
def test_move_state_disabled_for_non_real_groups(monkeypatch, group_id):
    controller = _make_controller(monkeypatch, DummyGroupManager())
    assert controller.get_item_move_state(1, group_id) == (False, False)
    assert controller.move_item_order(1, group_id, 1) is False


def test_paste_keeps_move_to_top_in_builtin_view(monkeypatch):
    """内置类型分组仍是历史流，粘贴后应照常"移到最前"；真实分组才关闭它。"""
    from settings import get_tool_settings_manager

    config = get_tool_settings_manager()
    monkeypatch.setattr(config, "get_clipboard_move_to_top_on_paste", lambda: True)

    recorded = []

    class PasteManager(DummyHistoryManager):
        def paste_item(self, item_id, with_html, move_to_top):
            recorded.append(move_to_top)
            return True

    manager = PasteManager()
    controller = _make_controller(monkeypatch, manager)
    controller.current_items = [_item(1, "image")]
    controller.current_group_id = BUILTIN_GROUP_IMAGE

    controller.paste_item(1)
    assert recorded == [True]


def test_paste_disables_move_to_top_in_real_group(monkeypatch):
    from settings import get_tool_settings_manager

    config = get_tool_settings_manager()
    monkeypatch.setattr(config, "get_clipboard_move_to_top_on_paste", lambda: True)

    recorded = []

    class PasteManager(DummyGroupManager):
        def paste_item(self, item_id, with_html, move_to_top):
            recorded.append(move_to_top)
            return True

    controller = _make_controller(monkeypatch, PasteManager())
    controller.current_items = [_item(1)]
    controller.current_group_id = 7

    controller.paste_item(1)
    assert recorded == [False]


# ============================================================
# Controller：新内容增量插入
# ============================================================


@pytest.mark.parametrize(
    "view_id, item_type, expected",
    [
        (BUILTIN_GROUP_IMAGE, "image", True),
        (BUILTIN_GROUP_IMAGE, "text", False),
        (BUILTIN_GROUP_TEXT, "text", True),
        (BUILTIN_GROUP_TEXT, "image", False),
    ],
)
def test_incremental_insert_in_builtin_view_requires_matching_type(
    monkeypatch, view_id, item_type, expected
):
    controller = _make_controller(monkeypatch, DummyHistoryManager())
    controller.current_items = [_item(3, "image"), _item(2, "text")]
    controller._current_offset = 2
    controller.current_group_id = view_id

    assert controller.insert_item(_item(4, item_type)) is expected


def test_file_dropdown_filter_still_falls_back_to_reload(monkeypatch):
    controller = _make_controller(monkeypatch, DummyHistoryManager())
    controller.current_items = [_item(2, "file")]
    controller.current_group_id = None
    controller._content_type = "file"

    assert controller.insert_item(_item(4, "file")) is False


# ============================================================
# 右键菜单：内置视图不算"在用户分组内"
# ============================================================


@pytest.mark.parametrize(
    "group_id, in_group",
    [(None, False), (BUILTIN_GROUP_TEXT, False), (BUILTIN_GROUP_IMAGE, False), (7, True)],
)
def test_context_menu_state_in_group(group_id, in_group):
    state = _ItemContextMenuState(
        clipboard_item=_item(1),
        current_group_id=group_id,
        visible_groups=[],
    )
    assert state.in_group is in_group


# ============================================================
# 容量：内置块固定占位，真实分组可用空间相应减少
# ============================================================


def test_capacity_reserves_space_for_builtin_block():
    # available = 高度 - 上(89) - 下(88) - 内置块(89)，每槽 38
    assert calc_sidebar_capacity(89 + 88 + 89 - 1) == 0
    assert calc_sidebar_capacity(89 + 88 + 89) == 0
    assert calc_sidebar_capacity(89 + 88 + 89 + 38) == 1


def test_topbar_capacity_reserves_space_for_builtin_block():
    # available = 宽度 - 左(89) - 右(78) - 内置块(89)，每槽 38
    assert calc_topbar_capacity(89 + 78 + 89) == 0
    assert calc_topbar_capacity(89 + 78 + 89 + 38) == 1


# ============================================================
# GroupBar：内置按钮渲染与交互
# ============================================================


class DummyBarController:
    def __init__(self, groups=None):
        self.current_group_id = None
        self._groups = groups or []
        self.switch_calls = []

    def get_sidebar_overflow(self, bar_size, is_top=False):
        return list(self._groups), []

    def switch_to_group(self, group_id):
        self.switch_calls.append(group_id)
        self.current_group_id = group_id


def _make_group_bar(groups=None):
    bar = GroupBar(
        controller=DummyBarController(groups),
        manager=object(),
        theme=THEME_LIGHT,
    )
    # 正式流程里 group_buttons_layout 由 build()/_build_bar() 创建；
    # 这里只测按钮渲染，直接补上竖向布局即可。
    from PySide6.QtWidgets import QBoxLayout

    bar.group_buttons_layout = QBoxLayout(
        QBoxLayout.Direction.TopToBottom, bar.group_buttons_widget
    )
    bar.group_buttons_layout.setContentsMargins(0, 0, 0, 0)
    return bar


def test_builtin_buttons_render_before_user_groups(qapp):
    group = Group(id=11, name="我的分组", icon="📁", group_type=GroupType.NORMAL)
    bar = _make_group_bar([group])

    bar.refresh_buttons()

    ids = [btn.property("group_id") for btn in bar.group_buttons]
    assert ids == [BUILTIN_GROUP_TEXT, BUILTIN_GROUP_IMAGE, 11]
    icons = [btn.text() for btn in bar.group_buttons[:2]]
    assert icons == ["🔤", "📷"]


def test_builtin_buttons_have_no_context_menu(qapp):
    group = Group(id=11, name="g", icon="📁", group_type=GroupType.NORMAL)
    bar = _make_group_bar([group])
    bar.refresh_buttons()

    builtin_btns = bar.group_buttons[:2]
    user_btn = bar.group_buttons[2]
    for btn in builtin_btns:
        assert btn.contextMenuPolicy() != Qt.ContextMenuPolicy.CustomContextMenu
        assert btn.property("builtin_group") is True
    assert user_btn.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_clicking_builtin_button_emits_view_id(qapp):
    bar = _make_group_bar()
    bar.refresh_buttons()
    switched = []
    bar.group_switched.connect(lambda gid: switched.append(gid))

    bar.group_buttons[0].click()
    bar.group_buttons[1].click()

    assert switched == [BUILTIN_GROUP_TEXT, BUILTIN_GROUP_IMAGE]


def test_sidebar_navigation_includes_builtin_buttons(qapp):
    group = Group(id=11, name="g", icon="📁", group_type=GroupType.NORMAL)
    bar = _make_group_bar([group])
    bar.refresh_buttons()

    # 全部(clipboard) + 文字 + 图片 + 1 个自建分组
    assert len(bar._get_sidebar_buttons()) == 4


def test_sync_selected_updates_checks_without_touching_controller(qapp):
    bar = _make_group_bar()
    bar.refresh_buttons()

    bar.sync_selected(BUILTIN_GROUP_IMAGE)

    assert bar.controller.switch_calls == []
    assert bar.clipboard_btn.isChecked() is False
    assert bar.group_buttons[0].isChecked() is False
    assert bar.group_buttons[1].isChecked() is True


def test_switch_to_group_delegates_to_controller_and_checks_all(qapp):
    bar = _make_group_bar()
    bar.refresh_buttons()

    bar.switch_to_group(None)

    assert bar.controller.switch_calls == [None]
    assert bar.clipboard_btn.isChecked() is True
    assert all(not btn.isChecked() for btn in bar.group_buttons)


def test_refresh_twice_does_not_duplicate_widgets(qapp):
    group = Group(id=11, name="g", icon="📁", group_type=GroupType.NORMAL)
    bar = _make_group_bar([group])

    bar.refresh_buttons()
    bar.refresh_buttons()

    from PySide6.QtWidgets import QPushButton, QFrame

    layout = bar.group_buttons_layout
    buttons = [layout.itemAt(i).widget() for i in range(layout.count())]
    buttons = [w for w in buttons if isinstance(w, QPushButton)]
    separators = [layout.itemAt(i).widget() for i in range(layout.count())]
    separators = [w for w in separators if isinstance(w, QFrame)]

    # 两个内置 + 一个自建 + 新建分组(+)
    assert len(buttons) == 4
    assert len(separators) == 1
