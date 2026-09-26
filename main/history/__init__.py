"""截图历史 / 继续标注。

把每次截图保存成可继续编辑的"工程"：完整虚拟桌面母片（source.png）、
标注工程状态（state.json）、列表缩略图（preview.jpg），三者由一个 SQLite
索引串起来。业务窗口只通过 HistoryManager 读写，不直接碰 SQLite 与文件 IO。
"""

from .models import SCHEMA_VERSION, HistoryRecord, STATUS_DRAFT, STATUS_READY
from .manager import HistoryManager, get_history_manager, shutdown_history_manager
from .annotation_codec import AnnotationCodec

__all__ = [
    "SCHEMA_VERSION",
    "HistoryRecord",
    "STATUS_DRAFT",
    "STATUS_READY",
    "HistoryManager",
    "get_history_manager",
    "shutdown_history_manager",
    "AnnotationCodec",
]