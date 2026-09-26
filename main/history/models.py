"""历史记录的数据模型与常量。"""

from dataclasses import dataclass


# state.json 的架构版本号。加字段不需要动它；字段语义发生不兼容变化时才 +1。
SCHEMA_VERSION = 1

# 记录状态：draft = 截图刚开始、还没确认选区；ready = 已是有效历史。
STATUS_DRAFT = "draft"
STATUS_READY = "ready"
# 数据缺失/损坏，列表里仍显示但不可继续标注。
STATUS_BROKEN = "broken"

# 第一版只有截图来源；"import" / "clipboard" 预留给以后，数据模型已经带这个字段。
SOURCE_SCREENSHOT = "screenshot"


@dataclass
class HistoryRecord:
    """一条历史记录的元数据（与 history.sqlite 的表结构一一对应）。"""

    id: str
    source_type: str = SOURCE_SCREENSHOT
    created_at: float = 0.0
    updated_at: float = 0.0
    source_path: str = ""
    state_path: str = ""
    preview_path: str = ""
    source_width: int = 0
    source_height: int = 0
    virtual_x: float = 0.0
    virtual_y: float = 0.0
    virtual_width: float = 0.0
    virtual_height: float = 0.0
    selection_x: float = 0.0
    selection_y: float = 0.0
    selection_width: float = 0.0
    selection_height: float = 0.0
    annotation_count: int = 0
    favorite: bool = False
    status: str = STATUS_DRAFT
    schema_version: int = SCHEMA_VERSION

    @property
    def virtual_rect(self):
        """虚拟桌面几何（x, y, w, h）。多屏时 x/y 可能是负数。"""
        return (
            float(self.virtual_x),
            float(self.virtual_y),
            float(self.virtual_width),
            float(self.virtual_height),
        )

    @property
    def favorite_int(self) -> int:
        return 1 if self.favorite else 0

    @classmethod
    def from_row(cls, row) -> "HistoryRecord":
        """由 sqlite3.Row 构造；列缺失或类型不符时用默认值兜底。"""
        def _get(name, default):
            try:
                value = row[name]
            except (IndexError, KeyError):
                return default
            return default if value is None else value

        return cls(
            id=str(_get("id", "")),
            source_type=str(_get("source_type", SOURCE_SCREENSHOT)),
            created_at=float(_get("created_at", 0.0)),
            updated_at=float(_get("updated_at", 0.0)),
            source_path=str(_get("source_path", "")),
            state_path=str(_get("state_path", "")),
            preview_path=str(_get("preview_path", "")),
            source_width=int(_get("source_width", 0)),
            source_height=int(_get("source_height", 0)),
            virtual_x=float(_get("virtual_x", 0.0)),
            virtual_y=float(_get("virtual_y", 0.0)),
            virtual_width=float(_get("virtual_width", 0.0)),
            virtual_height=float(_get("virtual_height", 0.0)),
            selection_x=float(_get("selection_x", 0.0)),
            selection_y=float(_get("selection_y", 0.0)),
            selection_width=float(_get("selection_width", 0.0)),
            selection_height=float(_get("selection_height", 0.0)),
            annotation_count=int(_get("annotation_count", 0)),
            favorite=bool(_get("favorite", 0)),
            status=str(_get("status", STATUS_DRAFT)),
            schema_version=int(_get("schema_version", SCHEMA_VERSION)),
        )