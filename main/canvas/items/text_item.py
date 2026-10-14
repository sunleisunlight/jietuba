"""文字图元。

描边、阴影、背景色块，以及编辑/候选/闲置的三态交互框。
"""
from __future__ import annotations

from math import acos, ceil, cos, pi, sin, sqrt

from PySide6.QtWidgets import (
    QGraphicsTextItem,
    QStyle, QStyleOptionGraphicsItem,
)
from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor, QFont, QTransform
from PySide6.QtCore import Qt, QPointF, QRect, QRectF, QSize
from core import log_debug, safe_event
from core.logger import T
from core.ui_scale import scaled_f

from .drawing_items import DrawingItemMixin


class TextItem(DrawingItemMixin, QGraphicsTextItem):
    """文字图元 - 增强版

    两种排版模式（Photoshop 式）：
    - point text（点文本）：``setTextWidth(-1)``，宽度随内容自然增长，换行只由
      手动回车决定。单击创建的文字走这一路。
    - paragraph text（段落文本）：``setTextWidth(宽度)``，右侧固定在拖出来的宽度
      上，文字排到右边界自动换行、内容变多时向下增高。拖拽创建的文字走这一路。

    模式不用 ``textWidth()`` 反推：-1 和"宽度恰好是 -1"在 Qt 里是同一件事，而
    "用户拖出来的段落宽度"是图元自身的性质，需要一个独立的字段记住它。
    """
    # 文字与交互框之间的内边距（document margin）
    TEXT_PADDING = 3
    MIN_POINT_SIZE = 6.0
    MAX_POINT_SIZE = 400.0
    CLICK_MARGIN = 2  # 点击/悬停旷量（像素/每侧），命中区比交互矩形略宽

    # 段落文本的最小排版宽度（100% UI 比例下的基准像素）。窄于这个宽度时每个
    # 汉字都会被挤到自己一行，看着像竖排，所以拖到再窄也按这个值兜底。
    BASE_MIN_PARAGRAPH_WIDTH = 48.0

    # 手柄 id：避开矩形(0-7)、圆角(10-13)、序号(200-202)
    HANDLE_ROTATE = 210
    HANDLE_DELETE = 211
    HANDLE_SCALE = 212
    HANDLE_TEXT_WIDTH = 213
    SCALE_HANDLE_SIZE = 10
    NORMAL_ANNOTATION_Z_VALUE = 20
    ANNOTATION_Z_VALUE = 30
    BACKGROUND_RADIUS = 6.0

    # 边框、命中区、四角按钮至少按这个宽度摆。空文字的文档区域只有 6px 左右，
    # 而左上旋转、右上删除两个按钮各 14px（LayerEditor.FUNCTIONAL_HANDLE_SIZE），
    # 按角点摆就会叠在一起，点下去谁响应都说不准。30px 让两者之间还剩 16px 空隙。
    # 放宽只加在右边：左边始终离文字起点一段固定距离（FRAME_SIDE_GAP），跟着宽度
    # 变的话，刚建出来的框会跳一下。
    MIN_INTERACTION_WIDTH = 30.0
    # 框离文字左右各让开这么多。文档边距只有 3px，框还要再往里让 1px、线宽 2px，
    # 不留空当的话，框就和闪烁的光标粘成一条：空文字框上光标贴着左边，打字时光标
    # 又贴着右边，两条线分不开。上下不用让——那两条边离光标本来就远。
    FRAME_SIDE_GAP = 4.0
    # 框往里让 1px，cosmetic 画笔的线宽才不会画到包围盒外面去（拖动会留残影）。
    FRAME_INSET = 1.0

    # 描边粗细只有四档，而且按字号的比例算，不是固定像素：同样 3px，在 12 号字上
    # 是一圈粗框，到 72 号字上细得几乎看不见。按比例算，拖右下角手柄把字放大时
    # 描边跟着等比变粗，同一档在任何字号下都是同一种观感。
    #
    # 档位按约 1.7 倍递增而不是等差：粗细的观感差异是对数的，等差档位在粗端分不
    # 出来。最粗一档在 16 号字上字眼仍然是通的，再粗字就糊成一团。
    OUTLINE_WIDTH_LEVELS = (0.04, 0.07, 0.12, 0.2)
    DEFAULT_OUTLINE_WIDTH = 0.07
    DEFAULT_OUTLINE_COLOR = "#FFFFFF"
    # 阴影朝右下偏移的距离，同样按字号比例算，理由同上
    SHADOW_OFFSET_RATIO = 0.08
    DEFAULT_SHADOW_COLOR = "#66000000"  # #AARRGGBB：黑色，40% 不透明

    # 描边用"把字形覆盖层整圈挪着叠一遍"叠出来（见 _paint_effects）：采样点越密越圆，
    # 每密一级就多叠一次覆盖层。正 K 边形外接圆半径 r 与边的最大偏差是
    # r(1 - cos(π/K))，按"偏差不超过 RING_MAX_ERROR_PX"反推 K，再夹在上下限之间。
    RING_MAX_ERROR_PX = 0.4
    RING_MIN_SAMPLES = 6
    RING_MAX_SAMPLES = 24

    def __init__(
        self,
        text: str,
        pos: QPointF,
        font: QFont,
        color: QColor,
        always_on_top: bool = True,
        provisional: bool = False,
    ):
        super().__init__(text)
        self._init_drawing_mixin()
        # 排版宽度：None = 点文本（宽度随内容增长），有值 = 段落文本（固定宽度换行）
        self._paragraph_width = None
        # 尺寸始终跟随内容：不设换行宽度，短内容才不会撑出多余的背景色。
        self.setTextWidth(-1)
        self.setPos(pos)
        self.setFont(font)
        self.setDefaultTextColor(color)
        # 允许点击编辑
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setZValue(
            self.ANNOTATION_Z_VALUE
            if always_on_top
            else self.NORMAL_ANNOTATION_Z_VALUE
        )
        
        # 增大 document margin，使虚线边框与文字之间有足够间距
        # 默认只有 4px，太小导致鼠标难以区分文字区域和边框区域
        self.document().setDocumentMargin(self.TEXT_PADDING)

        # 描边、阴影默认关闭；颜色是打开时的初始值（阴影的 alpha 即不透明度）
        self.has_outline = False
        self.outline_color = QColor(self.DEFAULT_OUTLINE_COLOR)
        self.outline_width = self.DEFAULT_OUTLINE_WIDTH
        self.has_shadow = False
        self.shadow_color = QColor(self.DEFAULT_SHADOW_COLOR)

        self.has_background = False # 默认关闭背景
        self.background_color = QColor(255, 255, 255, 255) # 白色全不透明

        # 临时文字：创建者没有推 AddItemCommand，把"是否真的创建"推迟到第一次
        # 失焦时按内容决定（见 focusOutEvent）。只有 TextTool 这样做，所以由它
        # 在创建时显式声明；其余路径（钉图克隆、测试）和其它图元一样创建即入栈，
        # 默认值对它们天然正确，不需要各自记得补一个标记。
        self._provisional = provisional
        # 每次进入编辑前的内容快照（见 focusInEvent）。清空后失焦要撤销，
        # 撤销栈上的 RemoveItemCommand 只会把图元加回场景，不知道它清空前
        # 写的是什么字——真正的文本得从这份快照里找回来。
        self._text_before_edit = text

    # ------------------------------------------------------------------
    # 字号缩放（右下角手柄驱动）
    # ------------------------------------------------------------------

    def font_point_size(self) -> float:
        """当前字号；点阵字体回退到用像素高度近似。"""
        size = self.font().pointSizeF()
        if size <= 0:
            size = float(self.font().pixelSize())
        return max(float(size), self.MIN_POINT_SIZE)

    def set_font_point_size(self, point_size: float):
        """按字号重新排版；描边粗细和阴影距离按字号比例算，跟着一起变。"""
        clamped = max(
            self.MIN_POINT_SIZE,
            min(self.MAX_POINT_SIZE, float(point_size)),
        )
        font = QFont(self.font())
        font.setPointSizeF(clamped)
        self.setFont(font)

    # ------------------------------------------------------------------
    # 排版模式：点文本 / 段落文本
    # ------------------------------------------------------------------

    @classmethod
    def min_paragraph_width(cls) -> float:
        """当前 UI 比例下段落文本的最小排版宽度。"""
        return max(1.0, scaled_f(cls.BASE_MIN_PARAGRAPH_WIDTH))

    def is_paragraph_text(self) -> bool:
        """是否是段落文本（固定宽度、右边界自动换行）。"""
        return self._paragraph_width is not None

    def paragraph_width(self) -> float | None:
        """段落宽度；点文本返回 None。"""
        return self._paragraph_width

    def set_paragraph_width(self, width):
        """切换排版宽度。

        - ``width`` 为 None → 回到点文本（``setTextWidth(-1)``，宽度随内容增长）
        - ``width`` 有值 → 段落文本，宽度钳到最小值以上

        改宽度会改变文档排版，包围盒、背景、命中区、四角手柄都跟着变，所以先
        ``prepareGeometryChange()`` 再动宽度。Qt 的 ``setTextWidth`` 内部也会
        触发一次失效，重复调用只是把小范围失效扩大成整图元失效，不影响正确性。
        """
        new_width = None if width is None else max(self.min_paragraph_width(), float(width))
        if new_width == self._paragraph_width and (
            (new_width is None and self.textWidth() < 0)
            or (new_width is not None and abs(self.textWidth() - new_width) < 1e-9)
        ):
            return

        self.prepareGeometryChange()
        self._paragraph_width = new_width
        self.setTextWidth(-1.0 if new_width is None else new_width)
        self.update()
        self._notify_layout_changed()

    def clear_paragraph_width(self):
        """退回到点文本模式。"""
        self.set_paragraph_width(None)

    def _notify_layout_changed(self):
        """排版变化后的扩展点。

        TextItem 自己不需要做别的事（Qt 会按新的文档尺寸重排），但 NoteItem 要
        在文本长高/变宽之后重新摆放文本框和箭头，所以留一个钩子。
        """
        return


    def get_edit_handles(self):
        """左上旋转、右上删除、右下缩放；段落文本再在右边中点加一个宽度手柄。

        锚点逐点 mapToScene 映射 local 包围盒的角，而不是取 sceneBoundingRect()
        的角：后者是轴对齐外包围盒，旋转之后它的角会甩到文字外面去（实测 45°
        偏 35px，137° 偏 239px），手柄既画错位置也点不到。

        按 interaction_rect() 摆而不是内容矩形：空文字只有 6px 宽，两个 14px 的
        按钮会叠在一起。
        """
        from canvas.handle_editor import EditHandle, HandleType, LayerEditor

        local = self.interaction_rect()
        handles = [
            EditHandle(
                self.HANDLE_ROTATE,
                HandleType.ROTATE,
                QPointF(self.mapToScene(local.topLeft())),
                Qt.CursorShape.SizeAllCursor,
                LayerEditor.FUNCTIONAL_HANDLE_SIZE,
            ),
            EditHandle(
                self.HANDLE_DELETE,
                HandleType.ITEM_DELETE,
                QPointF(self.mapToScene(local.topRight())),
                Qt.CursorShape.PointingHandCursor,
                LayerEditor.FUNCTIONAL_HANDLE_SIZE,
                2,
            ),
            EditHandle(
                self.HANDLE_SCALE,
                HandleType.TEXT_SCALE,
                QPointF(self.mapToScene(local.bottomRight())),
                Qt.CursorShape.SizeFDiagCursor,
                self.SCALE_HANDLE_SIZE,
                8,
            ),
        ]

        # 段落文本才需要宽度手柄：点文本的宽度由内容决定，没有可调的排版宽度
        if self.is_paragraph_text():
            handles.append(
                EditHandle(
                    self.HANDLE_TEXT_WIDTH,
                    HandleType.TEXT_WIDTH,
                    QPointF(self.mapToScene(QPointF(local.right(), local.center().y()))),
                    Qt.CursorShape.SizeHorCursor,
                    self.SCALE_HANDLE_SIZE,
                    8,
                )
            )
        return handles

    # ------------------------------------------------------------------
    # 描边与阴影
    # ------------------------------------------------------------------

    @classmethod
    def normalize_outline_width(cls, width) -> float:
        """把任意来源的描边粗细吸附到最近的档位（与 MosaicTool.clamp_block_size 同一个套路）。

        档位就是这个量的合法取值域：设置、面板、撤销记录、钉图克隆都经由这里，
        面板高亮的档和实际画出来的粗细才不会分家。正中间的平局取更粗的一档。
        """
        try:
            value = float(width)
        except (TypeError, ValueError):
            return cls.DEFAULT_OUTLINE_WIDTH
        return min(cls.OUTLINE_WIDTH_LEVELS, key=lambda level: (abs(level - value), -level))

    def outline_extent(self) -> float:
        """描边伸出字形之外的距离；没开描边为 0。"""
        return self.outline_width * self.font_point_size() if self.has_outline else 0.0

    def shadow_distance(self) -> float:
        """阴影往右、往下各挪多远；没开阴影为 0。"""
        return self.SHADOW_OFFSET_RATIO * self.font_point_size() if self.has_shadow else 0.0

    def outline_state(self) -> tuple:
        """(enabled, color, width)，与 set_outline 的参数一一对应，钉图克隆和面板回填原样取用。"""
        return (self.has_outline, QColor(self.outline_color), self.outline_width)

    def shadow_state(self) -> tuple:
        """(enabled, color)，与 set_shadow 的参数一一对应。"""
        return (self.has_shadow, QColor(self.shadow_color))

    def set_outline(self, enabled: bool, color: QColor = None, width: float = None):
        """开关描边。color / width 不传就沿用当前值；width 是档位（字号的比例）。"""
        self.prepareGeometryChange()
        self.has_outline = bool(enabled)
        if color is not None:
            self.outline_color = QColor(color)
        if width is not None:
            self.outline_width = self.normalize_outline_width(width)
        self.update()

    def set_shadow(self, enabled: bool, color: QColor = None):
        """开关阴影。color 不传就沿用当前值，它的 alpha 就是阴影的不透明度。"""
        self.prepareGeometryChange()
        self.has_shadow = bool(enabled)
        if color is not None:
            self.shadow_color = QColor(color)
        self.update()

    def document_rect(self) -> QRectF:
        """文档排版矩形：文字真正占的地方，不含描边、阴影、点击旷量。

        ``QGraphicsTextItem.boundingRect()`` 取的是文档当前排版出来的尺寸，段落
        文本下它的宽度就是 ``textWidth()``，所以这个矩形天然跟着排版模式变。
        显式写成基类调用，是因为子类（NoteItem）会重写 ``boundingRect()`` 去覆盖
        更大的范围。
        """
        return QGraphicsTextItem.boundingRect(self)

    def content_rect(self) -> QRectF:
        """文字真正画到的地方：文档区域再往外放出描边和阴影占的地方。

        描边、阴影都画在字形外面，粗档的描边远比 3px 的文档边距宽。包围盒不包住
        它们，重绘区就漏掉这一圈（拖动留残影、导出被裁掉），背景色块和四角手柄
        也会压进描边里。

        背景色块按这个矩形画，而不是 boundingRect()：后者为了摆得下四角按钮有最小
        宽度，窄字的背景跟着变宽就成了画面上看得见的差别，导出的图也跟着变。
        """
        rect = self.document_rect()
        outline = self.outline_extent()
        far_side = outline + self.shadow_distance()
        return rect.adjusted(-outline, -outline, far_side, far_side)

    def interaction_rect(self) -> QRectF:
        """交互用的矩形：内容矩形左右各让开 FRAME_SIDE_GAP，再至少放宽到 MIN_INTERACTION_WIDTH。

        边框、命中区、四角按钮都按它算；字画在哪里、背景画多大都不受它影响。
        """
        gap = self.FRAME_SIDE_GAP
        rect = QRectF(self.content_rect()).adjusted(-gap, 0, gap, 0)
        if rect.width() < self.MIN_INTERACTION_WIDTH:
            rect.setWidth(self.MIN_INTERACTION_WIDTH)
        return rect

    def hit_rect(self) -> QRectF:
        """命中/包围用的矩形：交互矩形再往外扩一圈点击旷量。

        文字是简单矩形几何，放大参数即可扩容差，不需要像箭头那样描边——
        旷量只用来扩点击/悬停判定，边框、四角按钮仍然按 interaction_rect()
        摆，不跟着放大。
        """
        return self.text_hit_rect()

    def text_hit_rect(self) -> QRectF:
        """只圈住"文字自己"的命中矩形，与目标框、箭头无关。

        NoteItem 会把 interaction_rect()/hit_rect() 重写成"整条标注"的范围，
        而它的 shape() 仍然需要一块只属于文字的命中区（否则框与文字之间的空白
        也会被算成命中，压在下面的标注就点不着了）。所以这里显式走 TextItem
        自己的算法，不经过那两个可能被重写的入口。
        """
        gap = self.FRAME_SIDE_GAP
        rect = QRectF(TextItem.content_rect(self)).adjusted(-gap, 0, gap, 0)
        if rect.width() < self.MIN_INTERACTION_WIDTH:
            rect.setWidth(self.MIN_INTERACTION_WIDTH)
        margin = self.CLICK_MARGIN
        return rect.adjusted(-margin, -margin, margin, margin)

    def boundingRect(self) -> QRectF:
        """包围盒按命中矩形算：必须完整覆盖 shape()，否则命中区会漏出包围盒外。"""
        return self.hit_rect()

    def shape(self) -> QPainterPath:
        """命中区跟着命中矩形走。

        QGraphicsTextItem.shape() 取的是它自己缓存的文档矩形，不会回头调用这里
        重写的 boundingRect()。不重写它，空文字框上放宽出来的那块就点不中——
        框看得见却点不着，比不放宽更糟。
        """
        path = QPainterPath()
        path.addRect(self.hit_rect())
        return path

    def contains(self, point: QPointF) -> bool:
        """命中判定同样按命中矩形来。

        QGraphicsTextItem.contains() 也是绕开 shape() 直接量它缓存的文档矩形的，
        场景的点击命中、view 里的"点在不在这段文字上"都走它，漏掉就等于没放宽。
        """
        return self.hit_rect().contains(point)

    @classmethod
    def ring_offsets_px(cls, radius_px: float) -> list[tuple[float, float]]:
        """描边外圈的采样偏移（覆盖层像素）。

        描边是"把字形覆盖层整圈挪着叠一遍"叠出来的，采样点越密越圆。正 K 边形外接
        圆半径 r 与边的最大偏差是 r(1 - cos(π/K))（实测 K=8、r=2px 时偏差 0.15px，肉
        眼看不见），按这个反推 K 再夹在上下限之间：细描边 8 个点就够，粗描边才加密，
        免得为了 0.4px 多叠十几次。
        """
        if radius_px <= 0.05:
            return []
        ratio = 1.0 - cls.RING_MAX_ERROR_PX / radius_px
        if ratio >= 1.0:
            count = cls.RING_MIN_SAMPLES
        else:
            count = int(ceil(pi / acos(max(-1.0, ratio))))
        count = max(cls.RING_MIN_SAMPLES, min(cls.RING_MAX_SAMPLES, count))
        step = 2.0 * pi / count
        return [(radius_px * cos(step * i), radius_px * sin(step * i)) for i in range(count)]

    def paint_text_coverage(self, painter, rect: QRectF):
        """把这段字按当前排版画进给定画笔，调用方只取它的覆盖（alpha）。

        用 ``document().drawContents()`` 而不是 ``QGraphicsTextItem.paint()``：后者会把
        选中高亮一起画进去，那块是不透明的大矩形，会在描边里凭空多出一个方框。
        画成什么颜色无所谓——覆盖层只当蒙版用。
        """
        area = self.document_rect().intersected(QRectF(rect))
        if area.isEmpty():
            return
        painter.save()
        try:
            self.document().drawContents(painter, area)
        finally:
            painter.restore()

    def _fx_layer(self, name: str, size: QSize) -> QImage:
        """按名字复用一块覆盖层画布；尺寸不够就换一块更大的。

        画布只增不减，所以每次用之前必须把"这次要用的那一块"清掉（见 _fx_clear），
        并且所有叠圈、着色都只在这块范围里做——不然复用下来的大画布会让每次叠圈都
        按整块算，白白多花几倍时间。

        不缓存结果：内容每次都可能变，缓存只在"打字时每键重建一次"这种场景下省一次
        计算，却要背一套失效逻辑；这里宁可每次重画，只复用缓冲，省掉的是每次分配的
        那几 MB 内存。
        """
        layer = getattr(self, name, None)
        if layer is None or layer.width() < size.width() or layer.height() < size.height():
            layer = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            setattr(self, name, layer)
        return layer

    @staticmethod
    def _fx_clear(layer: QImage, size: QSize):
        """清空这次要用的那一块（画布可能比它大）。

        必须是 Source 合成：默认的 SourceOver 画一层全透明等于什么都没做，旧内容会
        原封不动留在那儿。
        """
        painter = QPainter(layer)
        try:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(QRect(0, 0, size.width(), size.height()), QColor(0, 0, 0, 0))
        finally:
            painter.end()

    def _paint_effects(self, painter, option):
        """描边与阴影：画一次字形覆盖层，再靠位图叠圈做加粗。

        为什么不再沿字形轮廓描边：那要沿着整段字的轮廓走一圈笔，代价随字数增长而且
        常数极大——本机实测 2000 字一次 ``strokePath`` 要 2.7 秒、800 字 0.4 秒，而
        打字时每个按键都要重画整块，字一多就卡成幻灯片（40 字只要 4ms，所以"字少了
        不卡"）。改成"渲染一次覆盖层、再把它整圈叠几遍"之后，唯一的文字绘制交给 Qt
        自己的字形缓存（2000 字约 3ms），叠圈是纯位图操作、与字数无关；描边的外沿
        半径仍然是 ``outline_extent()``，观感和包围盒都不变。

        覆盖层按设备像素出图（用画笔当前的变换），所以缩放到多大都清晰；最后画回
        目标画笔时变换归零，覆盖层像素已经在设备坐标里了。
        """
        if option is None:
            return
        outline_extent = self.outline_extent()
        shadow_distance = self.shadow_distance()
        if outline_extent <= 0 and shadow_distance <= 0:
            return

        transform = painter.transform()
        scale = sqrt(abs(transform.determinant())) or 1.0
        exposed = QRectF(option.exposedRect)
        if exposed.isEmpty():
            # 自己造 QStyleOptionGraphicsItem 直接调 paint() 时（测试、导出）没有失效区，
            # 就按图元自己的范围算
            exposed = self.content_rect()
        # 覆盖层要比失效区多画一圈：叠圈和阴影都要用到失效区外面那点源像素，否则描边
        # 会在小块失效区（例如压在上面的手柄浮层重绘）边缘断掉。
        pad = (outline_extent + shadow_distance) * scale + 2.0
        device_rect = transform.mapRect(exposed).toAlignedRect()
        device_rect = device_rect.adjusted(-ceil(pad), -ceil(pad), ceil(pad), ceil(pad))
        if device_rect.isEmpty():
            return

        device = painter.device()
        dpr = device.devicePixelRatioF() if device is not None else 1.0
        px = QSize(
            max(1, round(device_rect.width() * dpr)),
            max(1, round(device_rect.height() * dpr)),
        )
        # 覆盖层像素相对图元单位的比例：描边粗细、阴影距离都按它换算
        unit = scale * px.width() / max(1.0, float(device_rect.width()))

        # 1) 字形覆盖层
        mask = self._fx_layer("_fx_mask", px)
        self._fx_clear(mask, px)
        mask_painter = QPainter(mask)
        try:
            mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            mask_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            # 先"逻辑设备 → 覆盖层像素"，再叠加"图元 → 逻辑设备"，顺序见 setTransform 的 combine
            mask_painter.scale(px.width() / device_rect.width(), px.height() / device_rect.height())
            mask_painter.translate(-device_rect.left(), -device_rect.top())
            mask_painter.setTransform(transform, True)
            self.paint_text_coverage(
                mask_painter,
                exposed.adjusted(-pad, -pad, pad, pad),
            )
        finally:
            mask_painter.end()

        # 2) 描边外圈：把覆盖层按采样点各挪一份叠起来取并集（Lighten 就是逐像素取最大
        #    透明度，正好等于"扩张"），得到外沿半径 = outline_extent 的加粗字形
        used = QRect(0, 0, px.width(), px.height())
        offsets = self.ring_offsets_px(outline_extent * unit)
        dilation = self._fx_layer("_fx_dilation", px)
        self._fx_clear(dilation, px)
        dilation_painter = QPainter(dilation)
        try:
            if offsets:
                dilation_painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Lighten
                )
                for dx, dy in offsets:
                    dilation_painter.drawImage(QPointF(dx, dy), mask, QRectF(used))
            else:
                dilation_painter.drawImage(QRectF(used), mask, QRectF(used))
        finally:
            dilation_painter.end()

        source = QRectF(0, 0, px.width(), px.height())

        # 3) 阴影：整块加粗字形（字形 + 描边带，与旧的画法一致）挪一段，整体涂阴影色
        shadow_layer = None
        if self.has_shadow and shadow_distance > 0:
            shadow_layer = self._fx_layer("_fx_shadow", px)
            self._fx_clear(shadow_layer, px)
            layer_painter = QPainter(shadow_layer)
            try:
                layer_painter.drawImage(QRectF(used), dilation, source)
                layer_painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceIn
                )
                layer_painter.fillRect(used, self.shadow_color)
            finally:
                layer_painter.end()

        # 4) 描边带：加粗字形挖掉字形本身，剩下的那圈涂描边色。挖掉字形是为了半透明的
        #    字不被描边色垫底——字缝里透出来的应该是背景，而不是一层描边色。
        ring_layer = None
        if self.has_outline and offsets:
            ring_layer = self._fx_layer("_fx_ring", px)
            self._fx_clear(ring_layer, px)
            layer_painter = QPainter(ring_layer)
            try:
                layer_painter.drawImage(QRectF(used), dilation, source)
                layer_painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_DestinationOut
                )
                layer_painter.drawImage(QRectF(used), mask, source)
                layer_painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceIn
                )
                layer_painter.fillRect(used, self.outline_color)
            finally:
                layer_painter.end()

        # 5) 贴回画布：覆盖层像素已经在设备坐标里，变换归零再按设备矩形落位
        painter.save()
        try:
            painter.setTransform(QTransform())
            if shadow_layer is not None:
                offset = shadow_distance * unit / max(1e-6, dpr)
                painter.drawImage(
                    QRectF(device_rect).translated(offset, offset), shadow_layer, source
                )
            if ring_layer is not None:
                painter.drawImage(QRectF(device_rect), ring_layer, source)
        finally:
            painter.restore()

    def paint(self, painter, option, widget):
        """由下往上：背景 → 阴影 → 描边 → 文字本身（含光标、选区）→ 交互框。"""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # 1. 绘制背景（如果在底层）
        if self.has_background:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.background_color)
            background_rect = self.content_rect()
            radius = min(
                self.BACKGROUND_RADIUS,
                max(0.0, background_rect.width() / 2.0),
                max(0.0, background_rect.height() / 2.0),
            )
            painter.drawRoundedRect(background_rect, radius, radius)
            painter.restore()

        if self.has_outline or self.has_shadow:
            self._paint_effects(painter, option)

        super().paint(painter, self._text_paint_option(option), widget)
        self._paint_interaction_frame(painter)

    # ------------------------------------------------------------------
    # 三态交互框
    # ------------------------------------------------------------------

    def is_editing(self) -> bool:
        """光标是否落在这段文字里（编辑态）。

        只看 textInteractionFlags 不够：文字新建出来就带着可编辑标志，钉图克隆、
        测试里造出来的文字从没获得过焦点，只凭标志会被当成"正在编辑"，平白画出
        一圈实线框。所以还要它确实是焦点图元；窗口失活时 hasFocus() 会变 False，
        这时看 scene 记的焦点图元。
        """
        if not (
            self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction
        ):
            return False
        scene = self.scene()
        return self.hasFocus() or (scene is not None and scene.focusItem() is self)

    def _text_paint_option(self, option):
        """摘掉选中/焦点状态位，再交给 Qt 画字。

        QGraphicsTextItem 自带的高亮是"选中就画一圈虚线"，分不出"正在编辑的这一段"
        和"点一下就能切过去的那一段"，还会和下面自己画的框叠成两圈。三态框统一由
        _paint_interaction_frame 负责。
        """
        if option is None:
            return option
        cleaned = QStyleOptionGraphicsItem(option)
        cleaned.state &= ~(
            QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus
        )
        return cleaned

    def is_edit_target(self) -> bool:
        """文字比别的图元多一个编辑态：光标落在这一段里，它就是当前对象。

        编辑态要单独算，光问控制器不够：TextTool 新建的那一段只 setFocus()，不走
        select_item()（见 tools/text.py），控制器那边此刻还是空的。
        """
        return super().is_edit_target() or self.is_editing()

    def _paint_interaction_frame(self, painter):
        """三态框画在交互矩形上；画不画、画成什么线型归 DrawingItemMixin。"""
        pen = self.selection_frame_pen()
        if pen is None:
            return
        inset = self.FRAME_INSET
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRect(self.interaction_rect().adjusted(inset, inset, -inset, -inset))
        painter.restore()

    def set_background(self, enabled: bool, color: QColor = None, opacity: int = None):
        self.has_background = enabled
        if color:
            self.background_color = QColor(color)
        if opacity is not None:
            self.background_color.setAlpha(int(max(0, min(255, opacity))))
        self.update()
        
    @safe_event
    def focusInEvent(self, event):
        """进入编辑前记一份内容快照。

        清空后失焦要撤销时，撤销栈上的命令得知道"清空前这里写的是什么字"才能
        真正找回来，而不只是把图元加回场景、留一个空壳——这份快照就是那个字的
        唯一来源，必须在还没被删之前存下来。
        """
        self._text_before_edit = self.toPlainText()
        super().focusInEvent(event)

    @safe_event
    def focusOutEvent(self, event):
        """失去焦点时的收尾：内容是否为空，决定这次退出编辑要不要在撤销栈上留痕。

        - 临时文字（刚创建、还没入栈）：空着失焦等于什么都没发生过，直接移出
          场景；有内容失焦才是它真正被创建出来的时刻，补推 AddItemCommand。
        - 已入栈的标注被编辑清空：这次清空本身是一次真实的删除，走
          ClearTextItemCommand 连清空前的文本一起记下，Ctrl+Z 才能找回内容，
          不能直接 removeItem 绕开撤销系统。
        """
        super().focusOutEvent(event)
        # 移除选中状态
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)

        scene = self.scene()
        undo_stack = getattr(scene, "undo_stack", None)

        if not self.toPlainText().strip():
            if scene is None:
                return
            if self._provisional or undo_stack is None:
                scene.removeItem(self)
                log_debug(T("内容为空，自动删除"), "TextItem")
            else:
                from canvas.undo import ClearTextItemCommand
                undo_stack.push(ClearTextItemCommand(scene, self, self._text_before_edit))
                log_debug(T("内容被清空，推入可撤销的删除"), "TextItem")
            return

        # 否则取消编辑模式（可选）
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        if self._provisional:
            self._provisional = False
            if undo_stack is not None:
                from canvas.undo import AddItemCommand
                undo_stack.push(AddItemCommand(scene, self))
            
    @safe_event
    def mouseDoubleClickEvent(self, event):
        """双击进入编辑模式"""
        if self.textInteractionFlags() == Qt.TextInteractionFlag.NoTextInteraction:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.setFocus()
        super().mouseDoubleClickEvent(event)

    def _is_on_text_edge(self, local_pos: QPointF) -> bool:
        """
        判断局部坐标是否在边框边缘（内边距及描边/阴影占的那一圈）
        在边缘 → True（应显示拖拽光标）
        在文字内容区域 → False（应显示文字编辑光标）
        """
        if not self.boundingRect().contains(local_pos):
            return False
        margin = self.document().documentMargin()
        inner = self.document_rect().adjusted(margin, margin, -margin, -margin)
        if inner.width() <= 0 or inner.height() <= 0:
            return True
        return not inner.contains(local_pos)

    def _apply_edit_cursor(self, local_pos: QPointF):
        """编辑态的光标：边缘那一圈是拖拽，文字区域是输入。"""
        if self._is_on_text_edge(local_pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.IBeamCursor)

    def hoverEnterEvent(self, event):
        """编辑中的光标自己分（工字/拖拽），其余交给通用的候选态处理。"""
        if self.is_editing():
            self._apply_edit_cursor(event.pos())
            event.accept()
            return
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        """同上：编辑中按位置区分工字和拖拽光标，不编辑就是普通候选。"""
        if self.is_editing():
            self._apply_edit_cursor(event.pos())
            event.accept()
            return
        super().hoverMoveEvent(event)

    # -- 统一属性接口 --

    def scale_stroke_width(self, scale: float) -> bool:
        """对文字图元，缩放字号"""
        font = self.font()
        point_size = font.pointSizeF()
        if point_size <= 0:
            point_size = float(font.pointSize() or 12)
        new_size = max(6.0, point_size * scale)
        font.setPointSizeF(new_size)
        self.setFont(font)
        self.update()
        return True

    def set_visual_opacity(self, opacity: float) -> bool:
        opacity = max(0.0, min(1.0, float(opacity)))
        self.setOpacity(opacity)
        self.update()
        return True

    def get_visual_opacity(self) -> float | None:
        return max(0.0, min(1.0, float(self.opacity())))

    # ------------------------------------------------------------------
    # 撤销快照扩展
    # ------------------------------------------------------------------

    def capture_extra_state(self) -> dict:
        """除 LayerEditor 默认字段外，本图元还要记进状态快照的字段。

        LayerEditor._copy_layer_state 会把这几个键并进同一份 dict，EditItemCommand
        回放时通过 restore_extra_state 还原——一份命令仍然只描述"一个图元"，不需要
        为段落宽度单开一种命令。
        """
        return {"paragraph_width": self._paragraph_width}

    def restore_extra_state(self, state: dict):
        """按快照还原本图元的扩展字段（state 可能是别的图元的，只取自己认识的键）。"""
        if "paragraph_width" in state:
            self.set_paragraph_width(state["paragraph_width"])
