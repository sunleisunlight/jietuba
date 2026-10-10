"""clipboard controllers 兼容导出。"""

from .context_menu_controller import ContextMenuData, MenuAction
from .clipboard_controller import (
    ClipboardController,
    calc_sidebar_capacity,
    calc_topbar_capacity,
    BUILTIN_GROUP_TEXT,
    BUILTIN_GROUP_IMAGE,
    BUILTIN_GROUP_IDS,
)
from .foreground_tracker import ForegroundWindowTracker
from .paste_keystroke import send_ctrl_v, set_foreground_window
from .selection_manager import SelectionManager

__all__ = [
    "ClipboardController",
    "ForegroundWindowTracker",
    "ContextMenuData",
    "MenuAction",
    "SelectionManager",
    "calc_sidebar_capacity",
    "calc_topbar_capacity",
    "BUILTIN_GROUP_TEXT",
    "BUILTIN_GROUP_IMAGE",
    "BUILTIN_GROUP_IDS",
    "send_ctrl_v",
    "set_foreground_window",
]