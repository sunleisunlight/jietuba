"""
文字工具

两种创建方式（Photoshop 式），区别只在鼠标怎么动：

- **单击** → 点文本（point text）：落点就是文字起点，宽度随内容自然增长，
  换行只由手动回车决定。
- **拖拽** → 段落文本（paragraph text）：拖出来的宽度就是排版宽度，文字排到右
  边界自动换行，内容变多时向下自然增高。

按下这一刻**不创建任何东西**：同一次按下既可能是单击也可能是拖框的开头，得等
松开才能定性（拖拽期间先给一圈虚线反馈框）。真正的"创建"仍然推迟到失焦时按内容
决定——点了没打字就点什么都没发生，撤销栈上不会留下空记录。

这段状态机因此有三个阶段：
    on_press   记下起点，进入 pending
    on_move    超过阈值 → 进入 paragraph drag，显示拖框反馈
    on_release 没超阈值走点文本，超了走段落文本；两者都直接进入输入状态
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont

from canvas.items import TextItem
from core.logger import T, log_debug

from .base import Tool, ToolContext
from .drag_preview import DragRectPreview


class TextTool(Tool):
    """
    文字工具（单机 = 点文本，拖拽 = 段落文本）
    """

    id = "text"

    # 按下之后挪过这么多像素才算"在拖框"，否则当成单击。和 SmartEditController
    # 的 drag_threshold 同一个量级——两处判断的是同一件事，差太多会出现"控制器
    # 认为在拖、工具认为在点"这种手感分裂。
    DRAG_THRESHOLD = 5

    # 拖框拖得比这个还窄就当误触，退回点文本。真正的下限由
    # TextItem.min_paragraph_width() 兜底，这里只管"这一下到底是不是在拖"。
    MIN_DRAG_EXTENT = DRAG_THRESHOLD

    def __init__(self):
        self.pending = False
        self.dragging = False
        self.start_pos = None
        self._preview = None

    # ------------------------------------------------------------------
    # 鼠标状态机
    # ------------------------------------------------------------------

    def on_press(self, pos: QPointF, button, ctx: ToolContext):
        if button != Qt.MouseButton.LeftButton:
            return
        self.pending = True
        self.dragging = False
        self.start_pos = QPointF(pos)

    def on_move(self, pos: QPointF, ctx: ToolContext):
        if not self.pending or self.start_pos is None:
            return
        if not self.dragging:
            if (pos - self.start_pos).manhattanLength() <= self.DRAG_THRESHOLD:
                return
            self.dragging = True
            self._preview = self._make_preview(ctx)
        if self._preview is not None:
            self._preview.update(pos)

    def on_release(self, pos: QPointF, ctx: ToolContext):
        if not self.pending:
            return

        start = self.start_pos
        was_dragging = self.dragging
        self._clear_preview(ctx)
        self.pending = False
        self.dragging = False
        self.start_pos = None
        if start is None:
            return

        rect = QRectF(start, pos).normalized()
        # 抖了一两个像素的"拖拽"其实是单击：交给点文本，不然会凭空多出一个
        # 贴着最小宽度的段落框
        if was_dragging and max(rect.width(), rect.height()) < self.MIN_DRAG_EXTENT:
            was_dragging = False

        if was_dragging:
            item = self._create_paragraph_item(rect, ctx)
        else:
            item = self._create_point_item(QPointF(start), ctx)
        if item is None:
            return

        self._enter_edit(item, ctx)

    def on_deactivate(self, ctx: ToolContext):
        """工具停用时收掉可能有残留的拖框反馈，并清除焦点以触发空文本自动删除"""
        self._clear_preview(ctx)
        self.pending = False
        self.dragging = False
        self.start_pos = None
        if ctx.scene.focusItem():
            ctx.scene.focusItem().clearFocus()

    # ------------------------------------------------------------------
    # 拖框反馈
    # ------------------------------------------------------------------

    def _make_preview(self, ctx: ToolContext):
        """拖框期间的一圈虚线，告诉用户"松手会得到这么大的排版宽度"。

        只是一层提示：不接受鼠标、不参与选中，松手前一定删掉，所以它不会进撤销栈，
        也不会被导出/钉图当成一条标注。
        """
        return DragRectPreview(ctx.scene, self.start_pos)

    def _clear_preview(self, ctx: ToolContext):
        preview, self._preview = self._preview, None
        if preview is not None:
            preview.clear()

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def _create_point_item(self, pos: QPointF, ctx: ToolContext):
        """单击创建：点文本。textWidth 保持 -1，宽度随内容增长。"""
        item = self._build_item(pos, ctx)
        if item is None:
            return None
        log_debug(T("创建文字: {pos}", pos=pos), "TextTool")
        return item

    def _create_paragraph_item(self, rect: QRectF, ctx: ToolContext):
        """拖拽创建：段落文本。拖出来的宽度 = 排版宽度，右边界自动换行。"""
        item = self._build_item(QPointF(rect.topLeft()), ctx)
        if item is None:
            return None
        # 宽度小于下限时 set_paragraph_width 会自己钳到 min_paragraph_width，
        # 于是"很窄的框"得到的是一个合理的最窄栏宽，而不是一行被挤成一列
        item.set_paragraph_width(rect.width())
        # 拖框可能把文字起点甩到选区外，夹回来（尺寸超标时贴住左上角）
        item.setPos(self._clamp_into_selection(item.pos(), item.document_rect().size(), ctx))
        log_debug(
            T("创建段落文字: {rect}", rect=rect),
            "TextTool",
        )
        return item

    def _build_item(self, pos: QPointF, ctx: ToolContext):
        """按设置造一个空的、临时的 TextItem 并放进场景。"""
        font = self._load_font(ctx)
        item = TextItem(
            "",
            pos,
            font,
            ctx.color,
            always_on_top=self._always_on_top(ctx),
            provisional=True,
        )
        self._apply_style_from_settings(item, ctx)
        ctx.scene.addItem(item)
        return item

    @staticmethod
    def _load_font(ctx: ToolContext) -> QFont:
        """从设置里读字体；管理器拿不到就退回默认字体。"""
        from settings import get_tool_settings_manager

        manager = get_tool_settings_manager()
        from core.constants import normalize_text_font_family

        font_family = normalize_text_font_family(
            manager.get_setting("text", "font_family", "")
        )
        font = QFont(font_family, manager.get_setting("text", "font_size", 16))
        font.setBold(manager.get_setting("text", "font_bold", False))
        font.setItalic(manager.get_setting("text", "font_italic", False))
        font.setUnderline(manager.get_setting("text", "font_underline", False))
        return font

    @staticmethod
    def _always_on_top(ctx: ToolContext) -> bool:
        from settings import get_tool_settings_manager

        manager = get_tool_settings_manager()
        return getattr(manager, "get_text_always_on_top_enabled", lambda: True)()

    @staticmethod
    def _apply_style_from_settings(item: TextItem, ctx: ToolContext):
        """描边、阴影、背景三件套照设置回填（与面板上显示的一致）。"""
        from settings import get_tool_settings_manager

        manager = get_tool_settings_manager()
        item.set_outline(
            manager.get_setting("text", "outline_enabled"),
            QColor(manager.get_setting("text", "outline_color")),
            manager.get_setting("text", "outline_width"),
        )
        item.set_shadow(
            manager.get_setting("text", "shadow_enabled"),
            QColor(manager.get_setting("text", "shadow_color")),
        )
        # 始终设置背景颜色（即使背景未启用），这样开启背景时会使用上次保存的颜色
        background_opacity = manager.get_setting("text", "background_opacity", 255)
        bg_color = QColor(manager.get_setting("text", "background_color", "#FFFFFF"))
        bg_color.setAlpha(int(background_opacity))
        item.set_background(
            manager.get_setting("text", "background_enabled", False),
            bg_color,
            int(background_opacity),
        )

    @staticmethod
    def _clamp_into_selection(top_left: QPointF, size, ctx: ToolContext) -> QPointF:
        """把文本框左上角夹进截图选区内；选区不可用时原样返回。"""
        selection = getattr(ctx, "selection", None)
        if selection is None:
            return QPointF(top_left)
        try:
            bounds = selection.rect()
        except Exception:
            return QPointF(top_left)
        if bounds is None or bounds.isEmpty():
            return QPointF(top_left)
        max_x = max(bounds.left(), bounds.right() - size.width())
        max_y = max(bounds.top(), bounds.bottom() - size.height())
        return QPointF(
            min(max(top_left.x(), bounds.left()), max_x),
            min(max(top_left.y(), bounds.top()), max_y),
        )

    def _enter_edit(self, item: TextItem, ctx: ToolContext):
        """自动进入编辑模式，光标置于末尾。

        这里仍然不推 AddItemCommand（上面以 provisional=True 声明）：这一刻内容还
        是空的，用户完全可能松手就点别处、什么都没打。真正的"提交到撤销栈"延后到
        TextItem.focusOutEvent 发现内容非空的那一刻——点了没打字的话，撤销栈上不会
        留下任何痕迹，不会平白吃掉用户后续的一次 Ctrl+Z。
        """
        item.setFocus()
        cursor = item.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        item.setTextCursor(cursor)

        # 通知智能编辑控制器选中该图元（以便显示二级菜单）
        ctx.scene.item_auto_select_requested.emit(item)
