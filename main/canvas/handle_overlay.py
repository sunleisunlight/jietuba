"""
手柄浮层 —— 编辑控制点的独立合成层。

为什么手柄不画在 QGraphicsScene 的 drawForeground 里：

控制点锚在图元包围盒的角上并向外凸出，它们不是 QGraphicsItem，不参与 Qt 的
失效核算。放在场景里意味着每个改动手柄的地方都得**猜**手柄能凸多远，再手写
一个外扩过的脏区（历史上就是 `margin = 25` 这个魔数）。猜错一次就是残影，而
且每加一种新手柄都要重新猜一次。

浮层把"猜"换成了"问"：失效范围直接取自每个手柄自己的 get_rect() —— 手柄画在
哪里，就失效到哪里，同一个真相源。

两个反直觉但必须遵守的约束（都是踩出来的）：

1. 浮层必须**永远铺满整个 viewport**，几何不能跟着手柄走。
   跟着手柄走的话，浮层几何就成了 (手柄 × viewportTransform × viewport 尺寸)
   的缓存投影，任何没通知到的 transform 变化（滚轮缩放、外部 setTransform）
   都会让它卡在旧矩形上，把手柄裁掉——比残影更糟，手柄直接消失。
   铺满之后几何只依赖 viewport 尺寸，不可能过期；而且视图变换导致整个 viewport
   重绘时，压在上面的浮层会被一并重绘，缩放自动就对了，一个通知都不需要。

2. 但**不能整层 update()**，也**不能用手柄的外接矩形**。浮层是半透明的，失效
   到哪，Qt 就把底下的内容层在**同一块地方**重绘到哪（实测整层失效和整场景重绘
   一样贵）；而一对手柄的外接矩形里往往只有边角上几小块是真的。备注就是最极端
   的例子：文字手柄在文字框上、目标框四角在屏幕另一头，外接矩形把中间一大片
   空白全圈进来，等于每敲一个字都把那一大片连内容层一起重绘一遍。所以失效区域
   一律按**单个手柄小方块的并集（区域，不是外接矩形）**算，并且并上上一次真正
   画过的区域好擦干净。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QRegion
from PySide6.QtWidgets import QWidget

from core import safe_event


class HandleOverlayWidget(QWidget):
    """绘制 LayerEditor 控制点的透明浮层，铺满 viewport，按手柄逐个失效。"""

    # 手柄描边 + 抗锯齿会溢出 get_rect() 一点点
    EDGE_ALLOWANCE = 3

    def __init__(self, view):
        super().__init__(view.viewport())
        self._view = view
        # 上一次画过的区域（viewport 坐标）：下次失效时要连它一起擦
        self._painted = QRegion()

        # 鼠标事件必须穿透，否则 view 收不到任何交互
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(False)

        self.setGeometry(view.viewport().rect())
        self.show()
        self.raise_()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _editor(self):
        controller = getattr(self._view, "smart_edit_controller", None)
        return getattr(controller, "layer_editor", None) if controller else None

    def _handles_viewport_region(self) -> QRegion:
        """每个手柄在 viewport 坐标下的绘制区域之并；没东西可画时返回空区域。

        范围由 LayerEditor.handle_rects() 逐个给出——它和 render() 挨在一起，
        所以浮层不需要知道 chrome 到底画了些什么。取并集而不是外接矩形，理由见
        模块开头第 2 条。
        """
        editor = self._editor()
        if editor is None:
            return QRegion()

        pad = self.EDGE_ALLOWANCE
        transform = self._view.viewportTransform()
        mine = self.rect()
        region = QRegion()
        for handle_rect in editor.handle_rects():
            painted = transform.mapRect(handle_rect).toAlignedRect()
            painted = painted.adjusted(-pad, -pad, pad, pad).intersected(mine)
            if painted.isEmpty():
                continue
            region = region.united(QRegion(painted))
        return region

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------
    def refresh(self):
        """手柄状态一变就调它：失效"新位置 ∪ 旧位置"。"""
        viewport_rect = self._view.viewport().rect()
        if self.geometry() != viewport_rect:
            # viewport 改尺寸了。整块重来，旧痕迹由这次全量失效带走。
            self.setGeometry(viewport_rect)
            self._painted = QRegion()
            self.update()
            return

        current = self._handles_viewport_region()
        dirty = current.united(self._painted)
        if not dirty.isEmpty():
            self.update(dirty)

    def _still_on_screen(self, repainted: QRegion, drawn: QRegion) -> QRegion:
        """这一帧过后，屏幕上还留着手柄像素的范围。

        不能直接记成"手柄现在在哪"：浮层压在 viewport 上，图元自己失效一小块
        就会顺带重绘这一块浮层，而这种被动重绘完全可能发生在图元几何已经变了、
        refresh() 还没轮到的中间态。

        所以按"这次重绘到底盖住了多少旧区域"来算：没盖全就把旧区域继续记着，
        下一次失效连它一起带走，然后自然收敛回精确值。
        """
        if self._painted.subtracted(repainted).isEmpty():
            return QRegion(drawn)
        return QRegion(drawn).united(self._painted)

    @safe_event
    def paintEvent(self, event):
        editor = self._editor()
        if editor is None or not editor.is_editing():
            self._painted = self._still_on_screen(event.region(), QRegion())
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # 浮层与 viewport 同尺寸同原点，所以 viewportTransform 直接可用
            painter.setWorldTransform(self._view.viewportTransform())
            editor.render(painter)
        finally:
            painter.end()

        # 视图变换导致的被动重绘也会走到这里，所以 _painted 始终反映屏幕上的
        # 真实情况，不依赖任何人来通知。
        self._painted = self._still_on_screen(
            event.region(), self._handles_viewport_region()
        )
