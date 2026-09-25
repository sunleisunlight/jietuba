"""备注（Note）图元 —— 目标框 + 箭头 + 文本框组成的复合标注。

对外仍然只算**一个逻辑标注**：创建、选中、删除、撤销、钉图克隆、导出全部按
"一个图元"处理。内部也没有各自独立的顶层图元：

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

**目标框和文本框是两个可以独立移动的主体**，箭头只是两者之间的派生连接器
（``arrow = connect(target, text)``，自己没有一个需要用户维护的自由状态）：

- 拖目标框：只动目标框，文字留在原地，箭头重新连接（``move_target_by_scene``）；
- 拖文字：只动文字（也就是本图元的 ``pos``），目标框靠本地坐标反向补偿留在原地
  （``move_text_by_scene``）。

子图元用 ``ItemStacksBehindParent`` 排在文字之后绘制，并关掉鼠标与悬停事件：
点击框、箭头、文字的任何可见部分都会命中 NoteItem 自己，具体抓的是哪一部分由
``hit_note_part`` 判定。

布局有 AUTO / FREE 两个模式（见 ``LAYOUT_AUTO`` / ``LAYOUT_FREE``）：刚创建时按
方向自动排版（用户看到的是"框 + 旁边一行说明"），用户第一次手工移动任何一个主体
之后进入自由布局，此后改文字、改字号、改排版宽度都只保留各自的位置、只重连箭头，
不会再被吸回自动位置。

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

    # 布局模式：AUTO = 按方向自动排版（创建时的聪明排版、方向按钮重排）；
    # FREE = 用户手工摆过位置，此后各主体位置独立、只重连箭头
    LAYOUT_AUTO = "auto"
    LAYOUT_FREE = "free"
    LAYOUT_MODES = (LAYOUT_AUTO, LAYOUT_FREE)

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
    # 文字主体的字号手柄。id 必须避开 TextItem(212/213) 与上面目标框四角(220-223)
    HANDLE_TEXT_SCALE = 214

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
        layout_mode: str = LAYOUT_AUTO,
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
        self._layout_mode = self.normalize_layout_mode(layout_mode)
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
        elif self._layout_mode == self.LAYOUT_FREE:
            # 自由布局的重建（钉图克隆）：各主体按传进来的几何原样摆好，只连箭头
            self._refresh_geometry()
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

    @classmethod
    def normalize_layout_mode(cls, value) -> str:
        """无法识别的布局模式回退到 AUTO（创建时的自动排版）。"""
        return value if value in cls.LAYOUT_MODES else cls.LAYOUT_AUTO

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

    @property
    def layout_mode(self) -> str:
        """AUTO（按方向自动排版）/ FREE（用户手工摆过位置）。"""
        return self._layout_mode

    def _enter_free_layout(self):
        """进入自由布局：目标框与文字的位置此后互相独立。"""
        self._layout_mode = self.LAYOUT_FREE

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
        """箭头两端的锚点：(文本侧, 目标侧)。

        - AUTO：按方向取各自靠近对方的边中点（和"文字在右边"的排版语义一致）；
        - FREE：用户已经把两个主体摆到任意相对位置，方向不再能描述几何，改成
          按"目标框中心 ↔ 文字框中心"这条射线分别求与两个矩形边界的交点——箭头
          永远连在两个矩形**面对彼此**的那条边上，文字挪到左上方也不会用错锚点。
        """
        if self._layout_mode == self.LAYOUT_FREE:
            return self._free_anchor_points(target, text_box)
        return self._direction_anchor_points(target, text_box)

    def _direction_anchor_points(self, target: QRectF, text_box: QRectF):
        """AUTO：文本侧、目标侧各取靠近对方的边中点。"""
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

    def _free_anchor_points(self, target: QRectF, text_box: QRectF):
        """FREE：两个中心连成一条射线，各自求它与自己矩形边界的交点。"""
        target_center = target.center()
        text_center = text_box.center()
        dx = text_center.x() - target_center.x()
        dy = text_center.y() - target_center.y()
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            # 两个中心完全重叠：射线不存在，退回方向语义，至少还有一对合法端点
            return self._direction_anchor_points(target, text_box)

        target_anchor = self._ray_rect_boundary(target, QPointF(dx, dy))
        text_anchor = self._ray_rect_boundary(text_box, QPointF(-dx, -dy))
        return (text_anchor, target_anchor)

    @staticmethod
    def _ray_rect_boundary(rect: QRectF, direction: QPointF) -> QPointF:
        """从矩形中心沿 direction 出发，与矩形边界的交点。

        direction 不必单位化，按"到任一轴边界所需的比例"取较小者即可；中心的
        一侧起点保证交点一定落在矩形的边上。矩形退化（宽或高为 0）、方向为零向量
        时都退回中心，不会算出 nan。
        """
        center = rect.center()
        half_w = rect.width() / 2.0
        half_h = rect.height() / 2.0
        dx, dy = float(direction.x()), float(direction.y())
        if half_w <= 0.0 or half_h <= 0.0:
            return QPointF(center)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return QPointF(center.x() + half_w, center.y())

        t_x = half_w / abs(dx) if abs(dx) > 1e-9 else float("inf")
        t_y = half_h / abs(dy) if abs(dy) > 1e-9 else float("inf")
        t = min(t_x, t_y)
        return QPointF(center.x() + dx * t, center.y() + dy * t)

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

    def _refresh_geometry(self):
        """按"当前 pos + 当前目标框本地矩形 + 当前文本尺寸"重连箭头。

        与 ``_relayout`` 的区别是**完全不动 pos、也不动目标框**：自由布局下改文字、
        改字号、改排版宽度、拖完目标框之后都走这里，两个主体各自留在用户放的地方，
        只有箭头作为派生几何跟着重算。
        """
        if getattr(self, "_target_item", None) is None:
            return
        origin = self.pos()
        target = QRectF(self._target_rect_local).translated(origin.x(), origin.y())
        box = self.document_rect()
        self.prepareGeometryChange()
        self._apply_local_geometry(target, QRectF(origin, box.size()), box.width(), box.height())

    def move_text_by_scene(self, delta_scene: QPointF):
        """只移动文字主体：目标框在场景里原地不动。

        本图元的 ``pos`` 就是文本框左上角，也是目标框本地坐标的原点。所以移动文字
        之后必须按"移动前目标框的场景矩形"反算一次本地坐标，让目标框在场景里保持
        原位——否则目标框会作为子图元跟着 pos 一起跑掉。
        """
        if getattr(self, "_target_item", None) is None:
            return
        dx, dy = float(delta_scene.x()), float(delta_scene.y())
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return

        target_scene = self.target_rect_scene()
        self.prepareGeometryChange()
        self.setPos(self.pos() + QPointF(dx, dy))
        self._target_rect_local = target_scene.translated(-self.pos().x(), -self.pos().y())
        self._target_item.setRect(self._target_rect_local)

        self._enter_free_layout()
        self._refresh_geometry()

    def move_target_by_scene(self, delta_scene: QPointF):
        """只移动目标框：文字（pos）完全不动。"""
        dx, dy = float(delta_scene.x()), float(delta_scene.y())
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        rect = self.target_rect_scene().translated(dx, dy)
        self.set_target_rect_scene_preserve_text(rect)

    def set_target_rect_scene_preserve_text(self, rect: QRectF):
        """把目标框改到给定的场景矩形上，文字位置保持不变，并进入自由布局。

        这是目标框移动 / 四角缩放的唯一入口。刻意不走 ``_text_origin()`` →
        ``setPos()`` 那条老路：那条路会把文字重新排到目标框旁边，用户手工摆好的
        两个主体就没法独立了。
        """
        if getattr(self, "_target_item", None) is None:
            return
        origin = self.pos()
        local = QRectF(rect).normalized().translated(-origin.x(), -origin.y())
        self._enter_free_layout()
        self._set_target_local(local)
        self._refresh_geometry()

    def _set_target_local(self, local: QRectF):
        self.prepareGeometryChange()
        self._target_rect_local = QRectF(local)
        self._target_item.setRect(self._target_rect_local)

    def fit_into(self, bounds: QRectF):
        """在给定范围内挑一个放得下目标框的方向与文本宽度，并摆好整条备注。

        创建备注时调用：默认方向右侧空间不够就先缩窄文本框，缩到最小宽度仍然
        放不下才翻到对面方向；四个方向都放不下时保留默认方向，再把整体夹回范围内，
        保证备注不会跑到截图选区外面去。
        """
        bounds = QRectF(bounds).normalized()
        # 创建 / 方向按钮重排都算自动排版，重新回到 AUTO
        self._layout_mode = self.LAYOUT_AUTO
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
        """文字内容变了：高度（可能还有行数）变了，得重连箭头。

        自由布局下只重连箭头、保留文字的左上角与目标框；自动布局下才按方向重排。
        这条分支就是"用户手工摆好文字之后再打字，文字不能跳回目标框旁边"的落点。
        """
        if self.scene() is None:
            return
        try:
            if self._layout_mode == self.LAYOUT_FREE:
                self._refresh_geometry()
            else:
                self._relayout()
        except Exception as exc:
            log_exception(exc, T("备注重排"))

    def _notify_layout_changed(self):
        """TextItem 的排版钩子：段落宽度变了 → 重连箭头（自动布局下才重排位置）。"""
        if getattr(self, "_target_item", None) is None:
            return
        if self._layout_mode == self.LAYOUT_FREE:
            self._refresh_geometry()
        else:
            self._relayout()

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------

    def set_direction(self, direction: str):
        """切换文本相对目标框的位置。

        方向按钮的语义是"我要重新自动排列"：目标框保持原位，文字按选择的方向重新
        摆好、箭头重新连接，并回到 AUTO 布局。此前手工拖出来的自由布局因此被显式
        覆盖——这正是用户点方向按钮的意图。
        """
        direction = self.normalize_position(direction)
        already_auto = self._layout_mode == self.LAYOUT_AUTO
        if direction == self._direction and already_auto:
            return
        self._direction = direction
        self._layout_mode = self.LAYOUT_AUTO
        self._relayout()

    def set_arrow_at(self, arrow_at: str):
        """箭头指向：目标 / 文字。只换指向，不改两个主体的位置。"""
        arrow_at = self.normalize_arrow_at(arrow_at)
        if arrow_at == self._arrow_at:
            return
        self._arrow_at = arrow_at
        if self._layout_mode == self.LAYOUT_FREE:
            self._refresh_geometry()
        else:
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
        """改字号：只动文字，不动目标框、不动线宽。

        字号决定文本框多高、箭头锚在哪，所以改完必须重连箭头；但不能顺手重排——
        自由布局下 `setFont` 本身就会保留文档左上角（正是我们要的"文字原地放大"），
        再重排就会把用户摆好的文字吸回目标框旁边。
        """
        self.set_font_point_size(point_size)
        if self._layout_mode == self.LAYOUT_FREE:
            self._refresh_geometry()
        else:
            self._relayout()

    def set_arrow_style(self, style: str):
        self._arrow_item.arrow_style = style
        if self._layout_mode == self.LAYOUT_FREE:
            self._refresh_geometry()
        else:
            self._relayout()

    def note_stroke_width(self) -> float:
        return float(self._stroke_width)

    def arrow_style(self) -> str:
        return self._arrow_item.arrow_style

    def set_target_rect_scene(self, rect: QRectF):
        """直接改写目标框（场景坐标）。

        等价于 ``set_target_rect_scene_preserve_text``：文字位置保持不动。历史上这里
        会把文字重新排到目标框旁边，是"拖目标框文字跟着跑"的根源，已改掉。
        """
        self.set_target_rect_scene_preserve_text(rect)

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
        标注就点不到了；所以命中区是"文字自身的框 + 目标框 + 箭头轮廓"的并集。

        唯一的例外是**这条备注已被选中**时：目标框的空心内部也算命中区。框是空心的，
        用户看到的是一个矩形，想拖它却要正好压在 1~3px 的边线上，不符合任何软件的
        习惯；选中态下把整框让给拖动，同时因为"只有当前对象"才有这个特权，压在下面
        的标注不会在平时被它挡住。
        """
        path = QPainterPath()
        # 显式走基类的"纯文字命中矩形"：NoteItem 自己把 hit_rect()/interaction_rect()
        # 重写成了"整条备注的外接矩形"，直接用会把框与箭头之间的空白也圈进命中区
        path.addRect(TextItem.text_hit_rect(self))
        target = getattr(self, "_target_item", None)
        if target is not None:
            if self.is_edit_target():
                path.addRect(self._target_rect_local)
            else:
                path.addPath(target.shape())
        arrow = getattr(self, "_arrow_item", None)
        if arrow is not None:
            path.addPath(arrow.shape())
        return path

    def contains(self, point: QPointF) -> bool:
        return self.shape().contains(point)

    def hit_note_part(self, scene_pos: QPointF):
        """这个场景点在备注的哪一部分上："text" / "target" / "arrow" / None。

        优先级 text > target > arrow：文字压在框上（自由布局允许重叠）时按文字算，
        免得用户想改文字却被判成在拖框。箭头只是派生连接器，排最后。
        """
        local = self.mapFromScene(scene_pos)
        if TextItem.text_hit_rect(self).contains(local):
            return "text"
        if QRectF(self._target_rect_local).contains(local):
            return "target"
        arrow = getattr(self, "_arrow_item", None)
        if arrow is not None and arrow.shape().contains(local):
            return "arrow"
        return None

    def _update_hover_cursor(self, event=None):
        """悬停在选中的备注上时，按"抓的是哪一部分"给光标。

        目标框内部、文字上都是"可以拖着走"的 SizeAll；箭头只负责连接，给普通选择
        光标，免得让人以为它也能单独移动。
        """
        if self._can_show_hover() and self.is_edit_target() and event is not None:
            part = self.hit_note_part(self.mapToScene(event.pos()))
            self.setCursor(
                Qt.CursorShape.SizeAllCursor
                if part in ("text", "target")
                else Qt.CursorShape.ArrowCursor
            )
            event.accept()
            return
        super()._update_hover_cursor(event)

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

    def _paint_interaction_frame(self, painter):
        """整条备注的三态框画在**文字主体**自己身上，不圈整条备注的外接矩形。

        圈住"框 + 箭头 + 文字"的合并范围会画出一个很大的外框，看着像是只能整体
        移动；而这里要表达的是"这条备注当前是编辑对象"。目标框自己另有一圈框
        （``_paint_target_rect``），两个主体各自可见，谁也不埋没谁。
        """
        pen = self.selection_frame_pen()
        if pen is None:
            return
        inset = self.FRAME_INSET
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRect(
            TextItem.interaction_rect(self).adjusted(inset, inset, -inset, -inset)
        )
        painter.restore()

    def _text_handles_rect(self) -> QRectF:
        """文字主体自己的交互矩形（本地坐标）。

        目标框在右边时，整条备注的 ``interaction_rect()`` 会一路铺到框的最右边——
        拿它摆文字的手柄，宽度手柄就会跑到目标框边上。所有"属于文字"的手柄都必须
        按这个矩形摆。
        """
        return TextItem.interaction_rect(self)

    def get_edit_handles(self):
        """目标框四角 + 文字主体的删除 / 字号 / 宽度手柄。

        两个主体各有各的手柄，且都摆在自己身上：目标框四角围着目标框，文字的三类
        手柄围着文字。故意不给旋转手柄：整条备注的几何是"框 + 箭头 + 给定方向的
        文本框"，旋转之后方向语义就说不清了（箭头该旋转还是该重新指向？）。
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

        bounds = self._text_handles_rect()
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
                self.HANDLE_TEXT_SCALE,
                HandleType.TEXT_SCALE,
                QPointF(self.mapToScene(bounds.bottomRight())),
                Qt.CursorShape.SizeFDiagCursor,
                self.SCALE_HANDLE_SIZE,
                8,
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
        """LayerEditor 的扩展入口：目标框四角改框，文字手柄改字号 / 排版宽度。

        ``drag_to`` 每次都会先把图元恢复到"这次拖拽开始时"的状态，所以这里只需
        在当前值上叠加相对位移，不需要自己存基准。

        三条铁律，对应三个主体的三种手柄：
        - 目标框四角：只改框的大小，文字留在原地；
        - 文字宽度手柄：只改段落排版宽度（左边不动、向右伸缩）；
        - 文字字号手柄：只改字号，目标框与线宽都不动。
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
            # 走"保留文字位置"的入口：改框大小不该把文字重新排回框旁边
            self.set_target_rect_scene_preserve_text(rect)
            return

        if handle_id == self.HANDLE_TEXT_WIDTH:
            setter = getattr(self, "set_paragraph_width", None)
            current = self.paragraph_width()
            if callable(setter) and current is not None:
                setter(current + float(delta_scene.x()))
            return

        if handle_id == self.HANDLE_TEXT_SCALE:
            self._apply_text_scale_drag(delta_scene)

    def _apply_text_scale_drag(self, delta_scene: QPointF):
        """文字右下角手柄：按文字自身对角线的投影比例换算新的字号。

        基准矩形取**文字自己的**交互矩形（不是整条备注的外接矩形）：LayerEditor 的
        默认实现用的是整条备注的包围盒，目标框在右边时那条对角线会被拉长，同一个
        拖拽距离换算出来的缩放比例就偏小，手感对不上。
        ``drag_to`` 每次都先回到基准状态，所以基准矩形在整次拖拽里是稳定的，
        ``font_point_size()`` 读到的也始终是起始字号。
        """
        base_rect = self._text_handles_rect()
        base_size = self.font_point_size()
        diag = base_rect.bottomRight() - base_rect.topLeft()
        denom = diag.x() * diag.x() + diag.y() * diag.y()
        if denom <= 0.0:
            return
        moved = diag + delta_scene
        factor = (moved.x() * diag.x() + moved.y() * diag.y()) / denom
        if factor <= 0:
            factor = 0.01
        self.set_note_font_size(base_size * factor)

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
                "note_layout_mode": self._layout_mode,
                "note_target_rect": QRectF(self._target_rect_local),
                "note_gap": float(self._gap),
            }
        )
        return state

    def restore_extra_state(self, state: dict):
        target_rect = state.get("note_target_rect")
        direction = state.get("note_direction")
        arrow_at = state.get("note_arrow_at")
        layout_mode = state.get("note_layout_mode")

        self._direction = self.normalize_position(direction if direction is not None else self._direction)
        self._arrow_at = self.normalize_arrow_at(
            arrow_at if arrow_at is not None else self._arrow_at
        )
        if layout_mode is not None:
            self._layout_mode = self.normalize_layout_mode(layout_mode)
        if isinstance(target_rect, QRectF):
            self._target_rect_local = QRectF(target_rect)

        # 文字位置（pos）由 LayerEditor 的通用字段负责恢复，这里只管目标框与布局；
        # 因此投影回场景时不再改动 pos。
        super().restore_extra_state(state)
        self._relayout_target_only()

    def _relayout_target_only(self):
        """按当前 pos 把本地目标框重新投影到场景并重连箭头（不改动 pos）。"""
        self._refresh_geometry()

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
            "layout_mode": self._layout_mode,
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

        布局模式也跟着复制：用户手工摆成"目标框在左上、文字在右下"之后钉图，钉图
        里的备注必须还是那个样子，不能又按方向自动排回目标框右边。
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
            layout_mode=state["layout_mode"],
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
