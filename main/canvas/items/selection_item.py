"""
选区框 - 边框和控制点
"""

from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QPen, QColor, QBrush, QPainter, QCursor
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)
from canvas.selection_model import SelectionModel
from .text_item import TextItem
from core.logger import log_debug, T
from core.theme import get_theme, ThemeManager
from core import safe_event


class SelectionItem(QGraphicsItem):
    """
    选区框 - 显示边框和8个控制点
    Z-order: 15
    """
    
    # 手柄标识
    HANDLE_NONE = 0
    HANDLE_TOP_LEFT = 1
    HANDLE_TOP = 2
    HANDLE_TOP_RIGHT = 3
    HANDLE_LEFT = 4
    HANDLE_RIGHT = 5
    HANDLE_BOTTOM_LEFT = 6
    HANDLE_BOTTOM = 7
    HANDLE_BOTTOM_RIGHT = 8
    HANDLE_BODY = 9 # 移动整个选区

    CORNER_HANDLES = (HANDLE_TOP_LEFT, HANDLE_TOP_RIGHT,
                      HANDLE_BOTTOM_LEFT, HANDLE_BOTTOM_RIGHT)

    # 手柄在一条边上占掉的长度超过边长的这个比例，整组手柄就不画了：再挤下去
    # 手柄互相压住，也把选区里的内容盖没了。
    HANDLE_CROWDING_RATIO = 0.8

    # 控制点之间那段边框本身的热区宽度（物理像素，场景坐标与屏幕 1:1）。
    # 八个手柄只落在角点和边中点，选区一大，想抓边得先瞄准小圆点；边框外侧
    # 是遮罩区、没有标注，多让几像素好抓；内侧是绘图区，只盖到描边内沿，
    # 再多就会吞掉贴着边框的正常起笔。
    EDGE_BAND_OUTER = 8

    @property
    def edge_band_inner(self) -> int:
        """边框内侧热区：描边内沿再让 1px，至少 2px。"""
        return max(2, self.border_width // 2 + 1)

    def __init__(self, model: SelectionModel):
        super().__init__()
        self.setZValue(15)
        
        self._model = model
        # 只连几何：装饰的重绘由 SelectionOverlayWidget 自己监听 model 信号
        self._model.rectChanged.connect(self.update_bounds)
        
        # 可交互（用于拖拽调整选区）
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True) # 启用悬停事件以改变光标

        # 本项只提供命中区，不产生像素。设了这个标志 Qt 不再调 paint()，
        # 「装饰不进 scene.render()」就是结构保证，而不是靠 paint() 的空函数体。
        # 命中和事件不受影响；prepareGeometryChange() 标脏的那块区域也照旧。
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents, True)

        # 浮层装上后指向它的 refresh。装饰不再画在场景里，QGraphicsItem.update()
        # 已经什么都不会重绘，改动装饰外观的地方要走这里。
        self.repaint_requested = None

        self.active_handle = self.HANDLE_NONE
        self.start_pos = QPointF()
        self.start_rect = QRectF()
        
        log_debug(T("选区框创建"), "Canvas")
    
    @property
    def border_width(self) -> int:
        """选区边框笔宽（物理像素——场景用屏幕物理坐标，视图 transform 为 1:1）。

        描边居中跨在选区边界上，内外各占一半。每次取值都回主题单例读，
        用户在设置里改完下一次截图就生效，不必逐处通知。
        """
        return get_theme().selection_border_width

    @property
    def handle_size(self) -> int:
        """控制点直径（物理像素，也是命中判定半径，见 _hit_test），随手柄大小档位变化。"""
        return get_theme().selection_handle_diameter

    @property
    def handle_ring_width(self) -> int:
        """控制点白色外圈笔宽（物理像素），同样每次从主题单例读取。"""
        return get_theme().selection_handle_ring_width

    @property
    def handle_visual_diameter(self) -> int:
        """控制点连白色外圈在内的视觉直径（物理像素）。"""
        return self.handle_size + self.handle_ring_width

    def boundingRect(self) -> QRectF:
        """边界矩形"""
        if self._model.is_empty():
            return QRectF()
        
        rect = self._model.rect()
        # 扩展一点以包含边框和控制点
        return rect.adjusted(-20, -20, 20, 20)
    
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        """空实现：选区装饰由 SelectionOverlayWidget 画在遮罩之上。

        本项留在场景里只为接收鼠标事件（boundingRect 即命中区）。设了
        ItemHasNoContents，Qt 根本不会调到这里；保留空实现是为了直接调用它的
        地方（测试、以及历史上手动 paint 的路径）同样画不出东西。
        """
        return

    def request_repaint(self):
        """请求浮层重绘装饰。浮层没装上时是空操作。"""
        if self.repaint_requested is not None:
            self.repaint_requested()

    def visual_bounds(self) -> QRectF:
        """render() 会画到的范围（场景坐标）；没东西可画时返回空矩形。

        和 render() 挨在一起，浮层据此算失效区，不需要知道画的是什么。
        """
        if self._model.is_empty():
            return QRectF()
        # 边框描边外溢半个笔宽；手柄骑在边界上，外溢半径 + 白圈笔宽。
        # 手柄关掉时这里仍按手柄算，多留几像素失效区不会画出东西，也省一条分支。
        pad = max(self.border_width / 2.0,
                  self.handle_size / 2.0 + 1 + self.handle_ring_width)
        return self._model.rect().adjusted(-pad, -pad, pad, pad)

    def render(self, painter: QPainter):
        """绘制选区边框和控制点（场景坐标）。

        由 SelectionOverlayWidget 调用，不是 QGraphicsItem.paint。浮层压在遮罩
        之上，所以跨出选区边界的描边不会再被半透明黑压暗。
        """
        if self._model.is_empty():
            return

        rect = self._model.rect()

        # 绘制边框（每次从 theme 单例读取，确保颜色实时生效）
        # 边框关抗锯齿：矩形是轴对齐的，开了只会在小数坐标下把 6px 硬边糊成
        # 5px + 2 个过渡像素。而小数矩形是常态——补间的每一帧、锁定长宽比都会产生。
        tc = get_theme().theme_color
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(tc, self.border_width, Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        if self.handles_visible():
            self.draw_handles(painter, rect)

    def handles_visible(self) -> bool:
        """这一帧是否画控制点。圆角预览走另一条绘制路径，判断共用这里。

        不画的三种情况：拖拽中（降低渲染压力）、选区未确认（智能选区预览阶段
        的手柄是画蛇添足）、选区小到挤不下手柄（见 HANDLE_CROWDING_RATIO）。

        只管画不画——命中判定不看它，八个方向始终可拖，与「手柄档位关掉」一致。
        """
        if self._model.is_empty():
            return False
        if self._model.is_dragging or not self._model.is_confirmed:
            return False

        style = get_theme().selection_handle_style
        if style == ThemeManager.HANDLES_NONE:
            return False

        # 一条边上：全显示是两个角手柄各占半个身位加中点手柄一个，合计两个直径；
        # 只画四角时合计一个。手柄骑在边界上，两个方向的排布相同，取短边即可。
        occupied = self.handle_visual_diameter * (
            2 if style == ThemeManager.HANDLES_ALL else 1)
        rect = self._model.rect()
        return occupied <= min(rect.width(), rect.height()) * self.HANDLE_CROWDING_RATIO

    def draw_handles(self, painter: QPainter, rect: QRectF, skip_corners: bool = False):
        """绘制控制点。圆角预览也调这里，手柄档位和配色只有这一份实现。

        skip_corners=True 跳过四角（圆角模式下四角手柄贴不住弧线）。
        """
        style = get_theme().selection_handle_style
        if style == ThemeManager.HANDLES_NONE:
            return

        # 控制点是圆，抗锯齿必须开
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        handles = self._get_handle_positions(rect)
        outer_r = self.handle_size // 2 + 1
        inner_r = self.handle_size // 2
        brush_handle = QBrush(get_theme().theme_color)
        pen_handle_outer = QPen(QColor(255, 255, 255), self.handle_ring_width)
        for handle_id, pos in handles.items():
            if handle_id in self.CORNER_HANDLES:
                if skip_corners:
                    continue
            elif style == ThemeManager.HANDLES_CORNERS:
                continue

            # 外圈（白色边框 + 主题色填充）
            painter.setPen(pen_handle_outer)
            painter.setBrush(brush_handle)
            painter.drawEllipse(pos, outer_r, outer_r)

            # 内圈（纯主题色填充）
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pos, inner_r, inner_r)
    
    def _get_handle_positions(self, rect: QRectF) -> dict:
        """获取8个控制点的位置"""
        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()
        cx = rect.center().x()
        cy = rect.center().y()
        
        return {
            self.HANDLE_TOP_LEFT: QPointF(left, top),
            self.HANDLE_TOP: QPointF(cx, top),
            self.HANDLE_TOP_RIGHT: QPointF(right, top),
            self.HANDLE_LEFT: QPointF(left, cy),
            self.HANDLE_RIGHT: QPointF(right, cy),
            self.HANDLE_BOTTOM_LEFT: QPointF(left, bottom),
            self.HANDLE_BOTTOM: QPointF(cx, bottom),
            self.HANDLE_BOTTOM_RIGHT: QPointF(right, bottom),
        }
    
    def update_bounds(self, *_):
        """选区变化后同步命中区。

        boundingRect 是本项唯一还起作用的东西（鼠标命中区），必须让场景索引知道
        它变了。不再调 update()——paint 已是空实现。
        """
        self.prepareGeometryChange()

    def hoverMoveEvent(self, event):
        """鼠标悬停：改变光标形状"""
        # 如果不接受悬停事件，直接返回（由 Scene 控制）
        if not self.acceptHoverEvents():
            event.ignore()
            return

        if self._model.is_empty():
            super().hoverMoveEvent(event)
            return

        # 文本框有自己的编辑逻辑，不使用选区框的调整手柄
        if self._should_delegate_to_text(event.scenePos()):
            self.unsetCursor()
            event.ignore()
            super().hoverMoveEvent(event)
            return
        

        if not self._model.is_confirmed:
            # 智能选区预览状态，统一使用十字光标
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            super().hoverMoveEvent(event)
            return
            
        # 选区已确认，根据悬停位置显示不同的调整光标
        handle = self._hit_test(event.pos())
        self.setCursor(self.cursor_for_handle(handle))
        super().hoverMoveEvent(event)

    @classmethod
    def cursor_for_handle(cls, handle: int) -> QCursor:
        """每个手柄（含 HANDLE_BODY / HANDLE_NONE）对应的光标。

        悬停反馈和 View 层边缘热区共用这一份，两处看到的方向必须一致。
        """
        if handle in (cls.HANDLE_TOP_LEFT, cls.HANDLE_BOTTOM_RIGHT):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif handle in (cls.HANDLE_TOP_RIGHT, cls.HANDLE_BOTTOM_LEFT):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif handle in (cls.HANDLE_TOP, cls.HANDLE_BOTTOM):
            shape = Qt.CursorShape.SizeVerCursor
        elif handle in (cls.HANDLE_LEFT, cls.HANDLE_RIGHT):
            shape = Qt.CursorShape.SizeHorCursor
        elif handle == cls.HANDLE_BODY:
            shape = Qt.CursorShape.SizeAllCursor
        else:
            shape = Qt.CursorShape.ArrowCursor
        return QCursor(shape)

    @safe_event
    def mousePressEvent(self, event):
        """鼠标按下：开始调整"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._should_delegate_to_text(event.scenePos()):
                event.ignore()
                return
            self.active_handle = self._hit_test(event.pos())
            if self.active_handle != self.HANDLE_NONE:
                self.start_pos = event.scenePos()
                self.start_rect = self._model.rect()
                # 通知开始拖拽（用于隐藏工具栏等优化）
                self._model.start_dragging()
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()

    @safe_event
    def mouseMoveEvent(self, event):
        """鼠标移动：调整选区"""
        if self.active_handle == self.HANDLE_NONE:
            return

        new_rect = self.resize_rect(
            self.active_handle, self.start_rect, self.start_pos, event.scenePos()
        )
        self._model.set_rect(new_rect.normalized())
        event.accept()

    @staticmethod
    def resize_rect(
        handle: int, start_rect: QRectF, start_pos: QPointF, current_pos: QPointF
    ) -> QRectF:
        """按手柄方向，把 start_rect 从 start_pos 拖到 current_pos 后的矩形。

        返回值未规范化（往左/往上拖时宽高为负），调用方负责 normalized()。
        View 层接管边缘手势时复用同一份几何算法，两条路径不允许拉出不同的框。
        """
        dx = current_pos.x() - start_pos.x()
        dy = current_pos.y() - start_pos.y()

        new_rect = QRectF(start_rect)
        if handle == SelectionItem.HANDLE_BODY:
            new_rect.translate(dx, dy)
            return new_rect

        if handle in [SelectionItem.HANDLE_LEFT, SelectionItem.HANDLE_TOP_LEFT,
                      SelectionItem.HANDLE_BOTTOM_LEFT]:
            new_rect.setLeft(start_rect.left() + dx)
        if handle in [SelectionItem.HANDLE_RIGHT, SelectionItem.HANDLE_TOP_RIGHT,
                      SelectionItem.HANDLE_BOTTOM_RIGHT]:
            new_rect.setRight(start_rect.right() + dx)
        if handle in [SelectionItem.HANDLE_TOP, SelectionItem.HANDLE_TOP_LEFT,
                      SelectionItem.HANDLE_TOP_RIGHT]:
            new_rect.setTop(start_rect.top() + dy)
        if handle in [SelectionItem.HANDLE_BOTTOM, SelectionItem.HANDLE_BOTTOM_LEFT,
                      SelectionItem.HANDLE_BOTTOM_RIGHT]:
            new_rect.setBottom(start_rect.bottom() + dy)
        return new_rect

    @safe_event
    def mouseReleaseEvent(self, event):
        """鼠标释放：结束调整"""
        if self.active_handle != self.HANDLE_NONE:
            # 通知结束拖拽（用于显示工具栏等）
            self._model.stop_dragging()
        self.active_handle = self.HANDLE_NONE
        event.accept()

    def _hit_test(self, pos: QPointF) -> int:
        """检测点击了哪个部分"""
        rect = self._model.rect()
        handles = self._get_handle_positions(rect)
        
        # 检查控制点
        for handle_id, handle_pos in handles.items():
            # 简单的距离检测
            if (pos - handle_pos).manhattanLength() < self.handle_size:
                return handle_id
                
        # 检查是否在矩形内部
        if rect.contains(pos):
            return self.HANDLE_BODY
            
        return self.HANDLE_NONE

    def edge_handle_at(self, scene_pos: QPointF) -> int:
        """场景坐标下，这个点是否落在选区的边缘热区（8 个边/角）上。

        与 ``_hit_test`` 的区别：手柄之间那段边框也算命中——选区一大，边框
        比小圆点好找得多，整条边都该能直接拖。命中返回对应手柄 id；点在
        选区内部（HANDLE_BODY）、热区之外、选区未确认、或位置上压着文字
        图元时返回 HANDLE_NONE，把这一下让给后续流程（绘图 / 文字编辑）。
        """
        if self._model.is_empty() or not self._model.is_confirmed:
            return self.HANDLE_NONE
        # 文字压在边框上时让位于文字编辑，与本项原生鼠标路径同一条例外
        if self._should_delegate_to_text(scene_pos):
            return self.HANDLE_NONE

        handle = self._hit_test(self.mapFromScene(scene_pos))
        if handle not in (self.HANDLE_NONE, self.HANDLE_BODY):
            return handle

        rect = self._model.rect()
        outer = self.EDGE_BAND_OUTER
        inner = self.edge_band_inner
        if not rect.adjusted(-outer, -outer, outer, outer).contains(scene_pos):
            return self.HANDLE_NONE

        # 内外不对称：外侧让出 outer，内侧只让 inner
        near_left = rect.left() - outer <= scene_pos.x() <= rect.left() + inner
        near_right = rect.right() - inner <= scene_pos.x() <= rect.right() + outer
        near_top = rect.top() - outer <= scene_pos.y() <= rect.top() + inner
        near_bottom = rect.bottom() - inner <= scene_pos.y() <= rect.bottom() + outer

        # 角优先于边：角落一带斜向拖才顺手
        if near_left and near_top:
            return self.HANDLE_TOP_LEFT
        if near_right and near_top:
            return self.HANDLE_TOP_RIGHT
        if near_left and near_bottom:
            return self.HANDLE_BOTTOM_LEFT
        if near_right and near_bottom:
            return self.HANDLE_BOTTOM_RIGHT
        if near_left:
            return self.HANDLE_LEFT
        if near_right:
            return self.HANDLE_RIGHT
        if near_top:
            return self.HANDLE_TOP
        if near_bottom:
            return self.HANDLE_BOTTOM
        return self.HANDLE_NONE

    def _should_delegate_to_text(self, scene_pos: QPointF) -> bool:
        """检测当前位置是否覆盖文字图元，若是则让位于文字编辑"""
        scene = self.scene()
        if scene is None:
            return False

        for item in scene.items(scene_pos):
            if item is self:
                continue
            if not item.isVisible():
                continue
            if isinstance(item, (TextItem, QGraphicsTextItem)):
                return True
        return False
 