"""备注（Note）图元 —— 目标框 + 箭头 + 文本框组成的复合标注。

对外只算**一个逻辑标注**：创建、选中、移动、删除、撤销、钉图克隆、导出全部按
"一个图元"处理。之所以能这么干净，是因为内部没有各自独立的顶层图元：

    目标框(RectItem)   ── 子图元，不接受鼠标、不参与选中，只是画出来
    箭头(ArrowItem)    ── 同上
    文本框             ── 就是 NoteItem 自己（继承 TextItem）

也就是说，光标所在的这段文字**就是**这条备注，而不是它的一个附件。因此：

- 输入法、光标、选区、双击重入编辑、Ctrl+Z 走文字编辑的既有语义，不需要另写一套；
- 拖框创建后的"直接打字"就是给这个图元 setFocus；
- 段落宽度（右边界自动换行）直接复用 TextItem 的 paragraph text 模式；
- 撤销一次 = AddItemCommand / RemoveItemCommand / EditItemCommand 各一条命令，
  因为整条备注从头到尾只有一个 QGraphicsItem；
- 钉图克隆只需要重建这一个图元，不会漏掉框或箭头。

子图元用 ``ItemStacksBehindParent`` 排在文字之后绘制，并关掉鼠标与悬停事件：
点击框、箭头、文字的任何可见部分都会命中 NoteItem 自己。

方向（direction）指**文本框相对目标框的位置**，与 ArrowItem 的 arrow_style
（箭杆/箭头的造型）是两件不同的事。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from core.logger import log_exception, T
from core.ui_scale import scaled_f

from .arrow_item import ArrowItem
from .drawing_items import RectItem
from .text_item import TextItem


def is_composite_child(item) -> bool:
    """图元是否是复合标注（备注）挂在父图元身上的装饰性子图元。

    场景枚举（导出、钉图克隆）和智能编辑控制器都要把这类图元排掉，否则一条备注
    会被当成"根 + 子图元"共三条标注。

    **刻意不用 ``item.parentItem()`` 判断。** 在 PySide6 里，对一个"没有被 Python
    持有、只由场景拥有"的顶层图元调用它会改变所有权归属：场景随即放手，等
    ``scene.items()`` 返回的临时列表被回收，图元就跟着被销毁——聚光灯的黑色幕布
    正是这样凭空消失的（`SpotlightCurtain.of()` 每次都要重新造一张、暗度回落到
    默认值）。子图元在创建时带了 ``ItemStacksBehindParent``，"画在父图元之后"
    本来就是装饰性子图元的定义，用它判断既准确又没有这个副作用。
    """
    flags = getattr(item, "flags", None)
    if not callable(flags):
        return False
    try:
        return bool(flags() & QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
    except Exception:
        return False


class NoteItem(TextItem):
    """一条备注。目标框 + 箭头 + 文本框，对外表现为单一图元。"""

    # 文本框相对目标框的位置
    POSITION_RIGHT = "right"
    POSITION_LEFT = "left"
    POSITION_TOP = "top"
    POSITION_BOTTOM = "bottom"
    POSITIONS = (POSITION_RIGHT, POSITION_LEFT, POSITION_TOP, POSITION_BOTTOM)
    DEFAULT_POSITION = POSITION_RIGHT

    # 箭头指向：默认"文字 → 目标"
    ARROW_AT_TARGET = "target"
    ARROW_AT_TEXT = "text"

    # 相对位置 -> 面板图标/文案用的翻译键（由 NoteSettingsPanel 取用）
    POSITION_LABELS = {
        POSITION_RIGHT: "Text on right",
        POSITION_LEFT: "Text on left",
        POSITION_TOP: "Text above",
        POSITION_BOTTOM: "Text below",
    }

    # 100% UI 比例下的基准像素
    BASE_GAP = 14.0              # 目标框与文本框之间的间隙
    BASE_TEXT_WIDTH = 200.0      # 默认段落宽度
    BASE_MAX_TEXT_WIDTH = 520.0  # 段落宽度上限，避免拖成一条横贯全屏的带子
    BASE_MIN_ROOM = 26.0         # 上下方向至少要有这么高的空间才认为"放得下"

    HANDLE_TARGET_TL = 220
    HANDLE_TARGET_TR = 221
    HANDLE_TARGET_BR = 222
    HANDLE_TARGET_BL = 223

    def __init__(
        self,
        target_rect: QRectF,
        font: QFont,
        color: QColor,
        direction: str = DEFAULT_POSITION,
        text: str = "",
        paragraph_width: float = None,
        stroke_width: float = 3.0,
        arrow_style: str = ArrowItem.STYLE_SINGLE,
        arrow_at: str = ARROW_AT_TARGET,
        gap: float = None,
        fit_bounds: QRectF = None,
        always_on_top: bool = True,
        provisional: bool = True,
    ):
        """target_rect 是**场景坐标**下的目标框；fit_bounds 是允许摆放的选区。"""
        super().__init__(
            text,
            QPointF(0.0, 0.0),
            font,
            color,
            always_on_top=always_on_top,
            provisional=provisional,
        )

        self._direction = self.normalize_position(direction)
        self._arrow_at = self.normalize_arrow_at(arrow_at)
        self._gap = self.base_gap() if gap is None else max(0.0, float(gap))
        self._stroke_width = max(1.0, float(stroke_width))
        self._fit_bounds = QRectF(fit_bounds) if isinstance(fit_bounds, QRectF) else None

        # 目标框存**本地坐标**：整体拖动（Qt 的 ItemIsMovable 只改 pos）时，
        # 子图元跟着一起走，不需要额外的同步逻辑。
        target_local = self._mapped_target_local(target_rect)

        pen = self._build_stroke_pen(self._stroke_width)
        self._target_item = RectItem(target_local, pen)
        self._target_item.setParentItem(self)
        self._target_item.setFlag(
            self._target_item.GraphicsItemFlag.ItemStacksBehindParent, True
        )
        self._make_passive_child(self._target_item)

        arrow = ArrowItem(target_local.center(), target_local.center(), QPen(color, self._stroke_width), arrow_style)
        arrow.setParentItem(self)
        arrow.setFlag(arrow.GraphicsItemFlag.ItemStacksBehindParent, True)
        self._make_passive_child(arrow)
        self._arrow_item = arrow

        self._target_rect_local = target_local
        self._arrow_start_local = QPointF(target_local.center())
        self._arrow_end_local = QPointF(target_local.center())

        # 段落宽度（None = 点文本，但备注总是段落文本，见 NoteTool）
        self.set_paragraph_width(
            self.base_text_width() if paragraph_width is None else paragraph_width
        )

        if self._fit_bounds is not None:
            self.fit_into(self._fit_bounds)
        else:
            self._relayout()

        # 文字内容变化会改变文本框高度（也可能改变宽度上限内的换行行数），
        # 排完版要把箭头和位置重新算一遍
        document = self.document()
        if document is not None:
            self._contents_slot = self._on_contents_changed
            document.contentsChanged.connect(self._contents_slot)

    # ------------------------------------------------------------------
    # 归一化 / 基础值
    # ------------------------------------------------------------------

    @classmethod
    def normalize_position(cls, value) -> str:
        """无法识别的方向回退到默认（右），旧配置/脏数据不会把备注画没。"""
        return value if value in cls.POSITIONS else cls.DEFAULT_POSITION

    @classmethod
    def normalize_arrow_at(cls, value) -> str:
        return value if value in (cls.ARROW_AT_TARGET, cls.ARROW_AT_TEXT) else cls.ARROW_AT_TARGET

    @staticmethod
    def base_gap() -> float:
        return max(2.0, scaled_f(NoteItem.BASE_GAP))

    @staticmethod
    def base_text_width() -> float:
        return max(TextItem.BASE_MIN_PARAGRAPH_WIDTH, scaled_f(NoteItem.BASE_TEXT_WIDTH))

    @staticmethod
    def base_max_text_width() -> float:
        return max(NoteItem.base_text_width(), scaled_f(NoteItem.BASE_MAX_TEXT_WIDTH))

    @staticmethod
    def _make_passive_child(child):
        """子图元只负责画：不抢鼠标、不接悬停，点击一律落到 NoteItem 自己身上。"""
        child.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        child.setAcceptHoverEvents(False)
        child.setFlag(child.GraphicsItemFlag.ItemIsMovable, False)
        child.setFlag(child.GraphicsItemFlag.ItemIsSelectable, False)
        child.setCursor(Qt.CursorShape.ArrowCursor)

    def _build_stroke_pen(self, width: float) -> QPen:
        color = QColor(self.defaultTextColor())
        pen = QPen(color, max(1.0, float(width)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _mapped_target_local(self, target_rect: QRectF) -> QRectF:
        """把场景坐标的目标框换成以当前 pos 为原点的本地坐标。"""
        origin = self.pos()
        return QRectF(target_rect).normalized().translated(-origin.x(), -origin.y())

    # ------------------------------------------------------------------
    # 几何 / 布局
    # ------------------------------------------------------------------

    def target_rect_local(self) -> QRectF:
        """目标框在本地坐标里的矩形（副本）。"""
        return QRectF(self._target_rect_local)

    def target_rect_scene(self) -> QRectF:
        """目标框在场景坐标里的矩形——整体拖动之后它会跟着 pos 走。"""
        rect = self._target_rect_local
        top_left = self.mapToScene(rect.topLeft())
        return QRectF(top_left, rect.size())

    def text_box_scene(self) -> QRectF:
        """文本框在场景坐标里的矩形（不含描边/阴影余量）。"""
        box = self.document_rect()
        top_left = self.mapToScene(box.topLeft())
        return QRectF(top_left, box.size())

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def arrow_at(self) -> str:
        return self._arrow_at

    def _text_origin(self, target: QRectF, width: float, height: float) -> QPointF:
        """按方向和文本框尺寸算出文本框左上角（场景坐标）。"""
        gap = self._gap
        if self._direction == self.POSITION_LEFT:
            return QPointF(target.left() - gap - width, target.top())
        if self._direction == self.POSITION_TOP:
            return QPointF(target.center().x() - width / 2.0, target.top() - gap - height)
        if self._direction == self.POSITION_BOTTOM:
            return QPointF(target.center().x() - width / 2.0, target.bottom() + gap)
        return QPointF(target.right() + gap, target.top())

    def _anchor_points(self, target: QRectF, text_box: QRectF):
        """箭头两端的锚点：(文本侧, 目标侧)，都取各自靠近对方的边中点。"""
        if self._direction == self.POSITION_LEFT:
            return (
                QPointF(text_box.right(), text_box.center().y()),
                QPointF(target.left(), target.center().y()),
            )
        if self._direction == self.POSITION_TOP:
            return (
                QPointF(text_box.center().x(), text_box.bottom()),
                QPointF(target.center().x(), target.top()),
            )
        if self._direction == self.POSITION_BOTTOM:
            return (
                QPointF(text_box.center().x(), text_box.top()),
                QPointF(target.center().x(), target.bottom()),
            )
        return (
            QPointF(text_box.left(), text_box.center().y()),
            QPointF(target.right(), target.center().y()),
        )

    def _relayout(self):
        """按目标框当前位置、方向和当前文本尺寸重排文本框与箭头。

        target 取自 ``target_rect_scene()``（跟随 pos），所以整体拖动以后再排版
        不会把目标框甩回原处。
        """
        if getattr(self, "_target_item", None) is None:
            return

        target = self.target_rect_scene()
        box = self.document_rect()
        width, height = box.width(), box.height()
        origin = self._text_origin(target, width, height)

        self.prepareGeometryChange()
        self.setPos(origin)
        self._apply_local_geometry(target, QRectF(origin, box.size()), width, height)

    def _apply_local_geometry(self, target: QRectF, text_box: QRectF, width: float, height: float):
        """把已算好的场景几何落到本地坐标上（子图元 + 箭头端点）。"""
        self._target_rect_local = target.translated(-text_box.left(), -text_box.top())
        self._target_item.setRect(self._target_rect_local)

        text_anchor, target_anchor = self._anchor_points(target, text_box)
        if self._arrow_at == self.ARROW_AT_TEXT:
            start_scene, end_scene = target_anchor, text_anchor
        else:
            start_scene, end_scene = text_anchor, target_anchor

        left, top = text_box.left(), text_box.top()
        self._arrow_start_local = QPointF(start_scene.x() - left, start_scene.y() - top)
        self._arrow_end_local = QPointF(end_scene.x() - left, end_scene.y() - top)
        self._arrow_item.set_positions(self._arrow_start_local, self._arrow_end_local)
        self.update()

    def fit_into(self, bounds: QRectF):
        """在给定范围内挑一个放得下目标框的方向与文本宽度，并摆好整条备注。

        创建备注时调用：默认方向右侧空间不够就先缩窄文本框，缩到最小宽度仍然
        放不下才翻到对面方向；四个方向都放不下时保留默认方向，再把整体夹回范围内，
        保证备注不会跑到截图选区外面去。
        """
        bounds = QRectF(bounds).normalized()
        if bounds.isEmpty():
            self._relayout()
            return

        target = self.target_rect_scene()
        box = self.document_rect()
        height = box.height()
        gap = self._gap
        min_width = self.min_paragraph_width()
        default_width = self.base_text_width()
        max_width = min(self.base_max_text_width(), bounds.width())

        candidates = [self.DEFAULT_POSITION] + [
            pos for pos in self.POSITIONS if pos != self.DEFAULT_POSITION
        ]
        chosen = None
        for position in candidates:
            room = self._room_for(position, target, bounds, gap)
            if room is None:
                continue
            required = height if position in (self.POSITION_TOP, self.POSITION_BOTTOM) else min_width
            if room < required:
                continue
            chosen = position
            break

        if chosen is None:
            chosen = self.DEFAULT_POSITION

        self._direction = chosen
        room = self._room_for(chosen, target, bounds, gap)
        width = default_width
        if room is not None:
            width = min(default_width, room)
        width = max(min_width, min(max_width, width))

        self.prepareGeometryChange()
        self.set_paragraph_width(width)

        box = self.document_rect()
        origin = self._text_origin(target, box.width(), box.height())
        origin = self._clamp_origin(origin, box.size(), bounds)
        self.prepareGeometryChange()
        self.setPos(origin)
        self._apply_local_geometry(target, QRectF(origin, box.size()), box.width(), box.height())

    @staticmethod
    def _room_for(position: str, target: QRectF, bounds: QRectF, gap: float):
        """某个方向上还剩多少空间可以放文本框；方向不合法返回 None。"""
        if position == NoteItem.POSITION_RIGHT:
            return bounds.right() - target.right() - gap
        if position == NoteItem.POSITION_LEFT:
            return target.left() - bounds.left() - gap
        if position == NoteItem.POSITION_TOP:
            return target.top() - bounds.top() - gap
        if position == NoteItem.POSITION_BOTTOM:
            return bounds.bottom() - target.bottom() - gap
        return None

    @staticmethod
    def _clamp_origin(origin: QPointF, box_size, bounds: QRectF) -> QPointF:
        """把文本框左上角夹进范围内；框比范围还大时贴住左上角。"""
        max_x = max(bounds.left(), bounds.right() - box_size.width())
        max_y = max(bounds.top(), bounds.bottom() - box_size.height())
        return QPointF(
            min(max(origin.x(), bounds.left()), max_x),
            min(max(origin.y(), bounds.top()), max_y),
        )

    def _on_contents_changed(self):
        """文字内容变了：行数/高度可能变了，重排一次（RIGHT/LEFT 的 pos 不变）。"""
        if self.scene() is None:
            return
        try:
            self._relayout()
        except Exception as exc:
            log_exception(exc, T("备注重排"))

    def _notify_layout_changed(self):
        """TextItem 的排版钩子：段落宽度变了 → 重排文本框与箭头。"""
        self._relayout()

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------

    def set_direction(self, direction: str):
        """切换文本相对目标框的位置：保留文本与样式，只重排几何。"""
        direction = self.normalize_position(direction)
        if direction == self._direction:
            return
        self._direction = direction
        self._relayout()

    def set_arrow_at(self, arrow_at: str):
        """箭头指向：目标 / 文字。"""
        arrow_at = self.normalize_arrow_at(arrow_at)
        if arrow_at == self._arrow_at:
            return
        self._arrow_at = arrow_at
        self._relayout()

    def set_note_color(self, color: QColor):
        """备注统一颜色：目标框描边、箭头、正文用同一个颜色。"""
        color = QColor(color)
        self.setDefaultTextColor(color)
        self._stroke_color = color
        self._target_item.setPen(self._build_stroke_pen(self._stroke_width))
        self._arrow_item.color = color
        self._arrow_item.update()
        self.update()

    def set_note_stroke_width(self, width: float):
        self._stroke_width = max(1.0, float(width))
        pen = self._build_stroke_pen(self._stroke_width)
        self._target_item.setPen(pen)
        self._arrow_item.base_width = self._stroke_width
        self._arrow_item.update_geometry()
        self._arrow_item.update()
        self.update()

    def set_note_font_size(self, point_size: float):
        """改字号并重排。

        字号决定文本框多高、箭头锚在哪，不能只 setFont 了事——文档尺寸变了但
        文本框左上角还留在原处，箭头就会从文本框里穿过去。
        """
        self.set_font_point_size(point_size)
        self._relayout()

    def set_arrow_style(self, style: str):
        self._arrow_item.arrow_style = style
        self._relayout()

    def note_stroke_width(self) -> float:
        return float(self._stroke_width)

    def arrow_style(self) -> str:
        return self._arrow_item.arrow_style

    def set_target_rect_scene(self, rect: QRectF):
        """直接改写目标框（场景坐标），文本框和箭头跟着重排。"""
        target = QRectF(rect).normalized()
        box = self.document_rect()
        origin = self._text_origin(target, box.width(), box.height())
        self.prepareGeometryChange()
        self.setPos(origin)
        self._apply_local_geometry(target, QRectF(origin, box.size()), box.width(), box.height())

    # ------------------------------------------------------------------
    # 命中区 / 包围盒
    # ------------------------------------------------------------------

    def _content_bounds(self) -> QRectF:
        """整条备注在本地坐标里的可见范围（文本框 + 目标框 + 箭头）。"""
        rect = TextItem.content_rect(self)
        target = getattr(self, "_target_item", None)
        if target is not None:
            rect = rect.united(target.boundingRect())
        arrow = getattr(self, "_arrow_item", None)
        if arrow is not None:
            rect = rect.united(arrow.boundingRect())
        return rect

    def interaction_rect(self) -> QRectF:
        """交互框按整条备注算：选中时的框要圈住框、箭头和文字三部分。"""
        return self._content_bounds()

    def hit_rect(self) -> QRectF:
        margin = self.CLICK_MARGIN
        return self._content_bounds().adjusted(-margin, -margin, margin, margin)

    def boundingRect(self) -> QRectF:
        return self.hit_rect()

    def shape(self) -> QPainterPath:
        """只有看得见的部分算命中区。

        用整条备注的外接矩形当命中区会连框与箭头之间的空白一起吃掉，压在下面的
        标注就点不到了；所以命中区是"文字自身的框 + 目标框描边 + 箭头轮廓"的并集。
        """
        path = QPainterPath()
        # 显式走基类的"纯文字命中矩形"：NoteItem 自己把 hit_rect()/interaction_rect()
        # 重写成了"整条备注的外接矩形"，直接用会把框与箭头之间的空白也圈进命中区
        path.addRect(TextItem.text_hit_rect(self))
        target = getattr(self, "_target_item", None)
        if target is not None:
            path.addPath(target.shape())
        arrow = getattr(self, "_arrow_item", None)
        if arrow is not None:
            path.addPath(arrow.shape())
        return path

    def contains(self, point: QPointF) -> bool:
        return self.shape().contains(point)

    # ------------------------------------------------------------------
    # 绘制 / 手柄
    # ------------------------------------------------------------------

    def paint(self, painter, option, widget=None):
        """文字由基类画（背景、描边、阴影、三态框都在那儿）；框和箭头是子图元，
        由 Qt 在本图元之后按 ItemStacksBehindParent 画在下面。"""
        TextItem.paint(self, painter, self._text_option(option), widget)
        self._paint_target_rect(painter)

    def _text_option(self, option):
        """交给基类画字之前，摘掉选中/焦点状态位。

        和 TextItem._text_paint_option 同一个理由：QGraphicsTextItem 自带的高亮是
        "选中就画一圈虚线"，会和下面对整条备注自己画的三态框叠成两圈。这里只是
        换个名字转发一次，行为完全一致。
        """
        return self._text_paint_option(option)

    def _paint_target_rect(self, painter):
        """目标框的描边由 RectItem 子图元负责，这里只在它上面补一圈候选/选中框。"""
        pen = self.selection_frame_pen()
        if pen is None:
            return
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRect(self._target_item.rect())
        painter.restore()

    def get_edit_handles(self):
        """目标框四角 + 右上删除 + 文本右边中点宽度手柄。

        故意不给旋转手柄：整条备注的几何是"框 + 箭头 + 给定方向的文本框"，旋转
        之后方向语义就说不清了（箭头该旋转还是该重新指向？），与其给一个会让人
        迷惑的手柄，不如不给。
        """
        from canvas.handle_editor import EditHandle, HandleType, LayerEditor

        handles = []
        target = self._target_rect_local
        corners = (
            (self.HANDLE_TARGET_TL, target.topLeft(), Qt.CursorShape.SizeFDiagCursor),
            (self.HANDLE_TARGET_TR, target.topRight(), Qt.CursorShape.SizeBDiagCursor),
            (self.HANDLE_TARGET_BR, target.bottomRight(), Qt.CursorShape.SizeFDiagCursor),
            (self.HANDLE_TARGET_BL, target.bottomLeft(), Qt.CursorShape.SizeBDiagCursor),
        )
        for handle_id, point, cursor in corners:
            handles.append(
                EditHandle(
                    handle_id,
                    HandleType.CORNER_TL,
                    QPointF(self.mapToScene(point)),
                    cursor,
                    LayerEditor.HANDLE_SIZE,
                )
            )

        bounds = self.interaction_rect()
        handles.append(
            EditHandle(
                self.HANDLE_DELETE,
                HandleType.ITEM_DELETE,
                QPointF(self.mapToScene(bounds.topRight())),
                Qt.CursorShape.PointingHandCursor,
                LayerEditor.FUNCTIONAL_HANDLE_SIZE,
                2,
            )
        )
        handles.append(
            EditHandle(
                self.HANDLE_TEXT_WIDTH,
                HandleType.TEXT_WIDTH,
                QPointF(self.mapToScene(QPointF(bounds.right(), bounds.center().y()))),
                Qt.CursorShape.SizeHorCursor,
                self.SCALE_HANDLE_SIZE,
                8,
            )
        )
        return handles

    def apply_handle_drag(self, handle_id: int, delta_scene: QPointF, keep_ratio: bool):
        """LayerEditor 的扩展入口：目标框四角改框，宽度手柄改排版宽度。

        ``drag_to`` 每次都会先把图元恢复到"这次拖拽开始时"的状态，所以这里只需
        在当前值上叠加相对位移，不需要自己存基准。
        """
        if handle_id in (
            self.HANDLE_TARGET_TL,
            self.HANDLE_TARGET_TR,
            self.HANDLE_TARGET_BR,
            self.HANDLE_TARGET_BL,
        ):
            rect = QRectF(self.target_rect_scene())
            if handle_id == self.HANDLE_TARGET_TL:
                rect.setTopLeft(rect.topLeft() + delta_scene)
            elif handle_id == self.HANDLE_TARGET_TR:
                rect.setTopRight(rect.topRight() + delta_scene)
            elif handle_id == self.HANDLE_TARGET_BR:
                rect.setBottomRight(rect.bottomRight() + delta_scene)
            else:
                rect.setBottomLeft(rect.bottomLeft() + delta_scene)

            rect = rect.normalized()
            room = max(4.0, scaled_f(4.0))
            if rect.width() < room or rect.height() < room:
                return
            self.set_target_rect_scene(rect)
            return

        if handle_id == self.HANDLE_TEXT_WIDTH:
            setter = getattr(self, "set_paragraph_width", None)
            current = self.paragraph_width()
            if callable(setter) and current is not None:
                setter(current + float(delta_scene.x()))

    # ------------------------------------------------------------------
    # 统一属性接口
    # ------------------------------------------------------------------

    def shows_selection_frame(self) -> bool:
        return True

    def scale_stroke_width(self, scale: float) -> bool:
        """备注的"大小"是框/箭头的线宽，不动字号——面板上字号另有入口。"""
        self.set_note_stroke_width(self._stroke_width * float(scale))
        return True

    def set_stroke_width(self, width: float):
        self.set_note_stroke_width(width)

    def get_stroke_width(self) -> float | None:
        return self.note_stroke_width()

    def set_visual_opacity(self, opacity: float) -> bool:
        opacity = max(0.0, min(1.0, float(opacity)))
        self.setOpacity(opacity)
        self.update()
        return True

    def get_visual_opacity(self) -> float | None:
        return max(0.0, min(1.0, float(self.opacity())))

    # ------------------------------------------------------------------
    # 撤销快照
    # ------------------------------------------------------------------

    def capture_extra_state(self) -> dict:
        """备注在 LayerEditor 默认字段之外还要记的几何与样式。

        存成扁平字段并进同一份快照，EditItemCommand 回放时由 restore_extra_state
        取用——一次拖拽/一次方向变更仍然只有一条命令。
        """
        state = super().capture_extra_state()
        state.update(
            {
                "note_direction": self._direction,
                "note_arrow_at": self._arrow_at,
                "note_target_rect": QRectF(self._target_rect_local),
                "note_gap": float(self._gap),
            }
        )
        return state

    def restore_extra_state(self, state: dict):
        target_rect = state.get("note_target_rect")
        direction = state.get("note_direction")
        arrow_at = state.get("note_arrow_at")

        self._direction = self.normalize_position(direction if direction is not None else self._direction)
        self._arrow_at = self.normalize_arrow_at(
            arrow_at if arrow_at is not None else self._arrow_at
        )
        if isinstance(target_rect, QRectF):
            self._target_rect_local = QRectF(target_rect)

        super().restore_extra_state(state)
        self._relayout_target_only()

    def _relayout_target_only(self):
        """按当前 pos 把本地目标框重新投影到场景并重排（不改动 pos）。"""
        if getattr(self, "_target_item", None) is None:
            return
        origin = self.pos()
        target = QRectF(self._target_rect_local).translated(origin.x(), origin.y())
        box = self.document_rect()
        self.prepareGeometryChange()
        self._apply_local_geometry(
            target, QRectF(origin, box.size()), box.width(), box.height()
        )

    # ------------------------------------------------------------------
    # 克隆（钉图）
    # ------------------------------------------------------------------

    def export_state(self) -> dict:
        """可完整重建一条备注的状态快照。"""
        return {
            "text": self.toPlainText(),
            "font": QFont(self.font()),
            "color": QColor(self.defaultTextColor()),
            "direction": self._direction,
            "arrow_at": self._arrow_at,
            "gap": float(self._gap),
            "target_rect_local": QRectF(self._target_rect_local),
            "paragraph_width": self.paragraph_width(),
            "stroke_width": float(self._stroke_width),
            "arrow_style": self._arrow_item.arrow_style,
            "arrow_start_local": QPointF(self._arrow_start_local),
            "arrow_end_local": QPointF(self._arrow_end_local),
            "outline": self.outline_state(),
            "shadow": self.shadow_state(),
            "background": (bool(self.has_background), QColor(self.background_color)),
        }

    def clone(self) -> "NoteItem":
        """重建一条一模一样的备注（钉图用）。

        复制的是**本地几何**：目标框、箭头端点都按原样搬过去，克隆完再整体 setPos
        到钉图场景的对应位置，因此相对关系与源截图逐像素一致，也不会退化成散件。
        """
        state = self.export_state()
        clone = NoteItem(
            target_rect=QRectF(state["target_rect_local"]),
            font=QFont(state["font"]),
            color=QColor(state["color"]),
            direction=state["direction"],
            text=state["text"],
            paragraph_width=state["paragraph_width"],
            stroke_width=state["stroke_width"],
            arrow_style=state["arrow_style"],
            arrow_at=state["arrow_at"],
            gap=state["gap"],
            fit_bounds=None,
            provisional=False,
        )
        clone._target_rect_local = QRectF(state["target_rect_local"])
        clone._target_item.setRect(clone._target_rect_local)
        clone._arrow_start_local = QPointF(state["arrow_start_local"])
        clone._arrow_end_local = QPointF(state["arrow_end_local"])
        clone._arrow_item.set_positions(clone._arrow_start_local, clone._arrow_end_local)
        clone.setPos(self.pos())
        clone.setZValue(self.zValue())
        clone.setOpacity(float(self.opacity()))
        if state["outline"]:
            clone.set_outline(*state["outline"])
        if state["shadow"]:
            clone.set_shadow(*state["shadow"])
        enabled, background_color = state["background"]
        clone.set_background(enabled, QColor(background_color), background_color.alpha())
        clone.update()
        return clone
