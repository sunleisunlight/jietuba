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

        # 备注工具按次门控：游客每设备 20 次，登录后注册赠送 1000 次，会员不限。
        # 门控只读本地缓存瞬时返回；撞到墙才弹登录/会员窗，网络异常一律放行。
        if not self._pass_note_gate():
            return

        item = self._create_note(target_rect, ctx)
        if item is None:
            return
        # 成功拖出一条有效备注即记一次（乐观扣减、后台结算，不阻断输入）
        try:
            from account import get_account
            get_account().consume_note()
        except Exception:
            pass
        self._enter_edit(item, ctx)

    @staticmethod
    def _pass_note_gate() -> bool:
        """备注次数门控；需要登录/会员时弹对应对话框，用户完成则放行本次使用。"""
        try:
            from account import get_account
            from account.gate_dialog import require_login, require_membership
            from PySide6.QtWidgets import QApplication
        except Exception:
            return True   # 账号模块异常绝不影响截图主流程
        acc = get_account()
        if acc.can_create_note():
            return True
        parent = QApplication.activeWindow()
        if acc.note_gate_reason() == "login":
            ok = require_login(parent)
        else:
            ok = require_membership(parent)
        # 用户完成登录/开通后放行；若权益快照尚未刷新，刚登录也直接放行本次
        return ok or acc.is_logged_in

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
        # 场景坐标是物理像素，视图按 1/dpr 缩到屏幕（Retina 上 0.5）。
        # 备注的字号、线宽、间距必须反向放大 dpr，才能和屏幕分辨率成正比，
        # 否则在 2x 屏上只有 Windows 上一半大，"太细太小"。
        dpr = self._capture_dpr(ctx)
        font = self._load_font(manager, dpr)
        bounds = self._selection_bounds(ctx)
        paragraph_width = self._optional_size(manager.get_setting("note", "text_width", 0))
        gap = self._optional_size(manager.get_setting("note", "gap", 0))

        item = NoteItem(
            target_rect=target_rect,
            font=font,
            color=QColor(ctx.color),
            direction=manager.get_setting("note", "label_position", NoteItem.DEFAULT_POSITION),
            text="",
            paragraph_width=(paragraph_width or NoteItem.base_text_width()) * dpr,
            stroke_width=max(1.0, float(ctx.stroke_width) * dpr),
            arrow_style=manager.get_setting("note", "arrow_style", ArrowItem.STYLE_SINGLE),
            arrow_at=manager.get_setting("note", "arrow_head_at", NoteItem.ARROW_AT_TARGET),
            gap=(gap or NoteItem.base_gap()) * dpr,
            fit_bounds=bounds,
            always_on_top=self._always_on_top(manager),
            # 和文字图元同一套语义：这一刻内容还是空的，点一下不打字就当什么都没
            # 发生；真的写了字，失焦时才补一条 AddItemCommand。整条备注从头到尾
            # 只有一个 QGraphicsItem，所以撤销一次就是撤销一整条。
            provisional=True,
        )
        item.set_visual_opacity(float(ctx.opacity))
        # 正文底色：和文字工具一样始终写一遍（即使当前关着），这样下次打开底色时
        # 用的就是上次保存的那支颜色与不透明度
        background_opacity = int(manager.get_setting("note", "background_opacity", 178))
        background_color = QColor(manager.get_setting("note", "background_color", "#FFFFFF"))
        background_color.setAlpha(background_opacity)
        item.set_background(
            bool(manager.get_setting("note", "background_enabled", False)),
            background_color,
            background_opacity,
        )
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
    def _load_font(manager, dpr: float = 1.0) -> QFont:
        from core.constants import normalize_text_font_family

        family = normalize_text_font_family(manager.get_setting("note", "font_family", ""))
        size = manager.get_setting("note", "font_size", 14)
        try:
            size = float(size)
        except (TypeError, ValueError):
            size = 14.0
        return QFont(family, max(1, int(round(size * dpr))))

    @staticmethod
    def _capture_dpr(ctx: ToolContext) -> float:
        """场景单位对应的屏幕点数倒数：Retina=2，普通屏=1。

        截图场景用物理像素，视图按 display_scale（=1/dpr）缩小显示。备注的字号、
        线宽、间距按这个比例放大，才能和屏幕分辨率成正比。
        """
        try:
            views = ctx.scene.views()
            view = views[0] if views else None
            scale = float(view.display_scale()) if view is not None else 1.0
        except Exception:
            scale = 1.0
        return 1.0 / scale if 0.05 < scale <= 1.0 else 1.0

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
