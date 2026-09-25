"""
备注工具 —— 拖框圈住目标，松手自动生成"目标框 + 箭头 + 文本框"。

和矩形工具一样是"拖一个框出来"，区别在松手之后：矩形到此为止，备注还要把文本框、
箭头一起摆好，并**直接进入输入状态**——用户拖完立刻就能打字，不用再点一下。

这些几何关系全部由 NoteItem 负责（含"哪个方向放得下"的自动避让），工具这边只做
三件事：把拖出来的矩形交给它、把设置面板里的默认值读出来、把焦点给它。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont

from canvas.items import ArrowItem, NoteItem
from core.logger import T, log_debug

from .base import Tool, ToolContext
from .drag_preview import DragRectPreview


class NoteTool(Tool):
    """
    备注工具
    """

    id = "note"

    # 目标框最小边长（像素）。比这更小的一下按误触处理：一个 3x3 的目标框放大到
    # 100% 也就几个像素，箭头和文本框会把它整个盖住，等于什么都没标。
    MIN_SIZE = 12

    # 按下到移动超过这么多像素才算"在拖框"，否则当误触
    DRAG_THRESHOLD = 3

    def __init__(self):
        self.pending = False
        self.drawing = False
        self.start_pos = None
        self._preview = None

    # ------------------------------------------------------------------
    # 鼠标状态机
    # ------------------------------------------------------------------

    def on_press(self, pos: QPointF, button, ctx: ToolContext):
        if button != Qt.MouseButton.LeftButton:
            return
        self.pending = True
        self.drawing = False
        self.start_pos = QPointF(pos)

    def on_move(self, pos: QPointF, ctx: ToolContext):
        if not self.pending or self.start_pos is None:
            return
        if not self.drawing:
            if (pos - self.start_pos).manhattanLength() <= self.DRAG_THRESHOLD:
                return
            self.drawing = True
            self._preview = DragRectPreview(ctx.scene, self.start_pos)
        if self._preview is not None:
            self._preview.update(pos)

    def on_release(self, pos: QPointF, ctx: ToolContext):
        if not self.pending:
            return

        start = self.start_pos
        self.pending = False
        self.drawing = False
        self.start_pos = None
        self._clear_preview(ctx)

        if start is None:
            return
        # 任意方向拖都一样：normalized 之后左上角在左上
        target_rect = QRectF(start, pos).normalized()
        if target_rect.width() < self.MIN_SIZE or target_rect.height() < self.MIN_SIZE:
            log_debug(
                T("备注取消：目标框过小 ({width:.1f}x{height:.1f})",
                  width=target_rect.width(), height=target_rect.height()),
                "NoteTool",
            )
            return

        item = self._create_note(target_rect, ctx)
        if item is None:
            return
        self._enter_edit(item, ctx)

    def on_deactivate(self, ctx: ToolContext):
        """工具停用时收掉可能残留的拖框反馈，并让正在输入的备注结算内容"""
        self._clear_preview(ctx)
        self.pending = False
        self.drawing = False
        self.start_pos = None
        if ctx.scene.focusItem():
            ctx.scene.focusItem().clearFocus()

    # ------------------------------------------------------------------
    # 拖框反馈
    # ------------------------------------------------------------------

    def _clear_preview(self, ctx: ToolContext):
        preview, self._preview = self._preview, None
        if preview is not None:
            preview.clear()

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def _create_note(self, target_rect: QRectF, ctx: ToolContext):
        """按设置造一条备注并放进场景（内容为空，等用户输入）。"""
        from settings import get_tool_settings_manager

        manager = get_tool_settings_manager()
        font = self._load_font(manager)
        bounds = self._selection_bounds(ctx)

        item = NoteItem(
            target_rect=target_rect,
            font=font,
            color=QColor(ctx.color),
            direction=manager.get_setting("note", "label_position", NoteItem.DEFAULT_POSITION),
            text="",
            paragraph_width=self._optional_size(manager.get_setting("note", "text_width", 0)),
            stroke_width=max(1.0, float(ctx.stroke_width)),
            arrow_style=manager.get_setting("note", "arrow_style", ArrowItem.STYLE_SINGLE),
            arrow_at=manager.get_setting("note", "arrow_head_at", NoteItem.ARROW_AT_TARGET),
            gap=self._optional_size(manager.get_setting("note", "gap", 0)),
            fit_bounds=bounds,
            always_on_top=self._always_on_top(manager),
            # 和文字图元同一套语义：这一刻内容还是空的，点一下不打字就当什么都没
            # 发生；真的写了字，失焦时才补一条 AddItemCommand。整条备注从头到尾
            # 只有一个 QGraphicsItem，所以撤销一次就是撤销一整条。
            provisional=True,
        )
        item.set_visual_opacity(float(ctx.opacity))
        ctx.scene.addItem(item)
        log_debug(T("创建备注: {rect}", rect=target_rect), "NoteTool")
        return item

    @staticmethod
    def _optional_size(value):
        """"自动"在设置里存成 0——QSettings 存不了 None，0 表示交给 NoteItem 按
        当前 UI 比例自己算（见 NoteItem.base_text_width / base_gap）。"""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _load_font(manager) -> QFont:
        from core.constants import normalize_text_font_family

        family = normalize_text_font_family(manager.get_setting("note", "font_family", ""))
        return QFont(family, manager.get_setting("note", "font_size", 14))

    @staticmethod
    def _always_on_top(manager) -> bool:
        """备注里就装着一段文字，所以跟着"文字始终置顶"这个既有开关走，
        不为它单开一个全局设置。"""
        return getattr(manager, "get_text_always_on_top_enabled", lambda: True)()

    @staticmethod
    def _selection_bounds(ctx: ToolContext):
        """允许摆放的范围 = 当前截图选区；拿不到就返回 None（不夹取）。"""
        selection = getattr(ctx, "selection", None)
        if selection is None:
            return None
        try:
            rect = selection.rect()
        except Exception:
            return None
        if rect is None or rect.isEmpty():
            return None
        return QRectF(rect)

    def _enter_edit(self, item: NoteItem, ctx: ToolContext):
        """直接进入输入状态：拖完就能打字。"""
        item.setFocus()
        cursor = item.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        item.setTextCursor(cursor)

        # 通知智能编辑控制器选中该图元（弹出备注二级面板）
        ctx.scene.item_auto_select_requested.emit(item)
