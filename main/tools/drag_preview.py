"""拖框时的虚线反馈框。

矩形、椭圆这类工具是"边拖边画真图元"，反馈就是图元本身。文字和备注不行：松手
之前根本不知道这次会得到点文本还是段落文本、目标框要不要接一支箭头，没有一个
"半成品"能代表最终结果。于是给它们一个只负责提示的虚线框。

这个框只活在拖拽期间：不接受鼠标、不参与选中，松手前必定删除，所以它不会进撤销
栈，也不会被导出或钉图当成一条标注。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from canvas.items import RectItem


class DragRectPreview:
    """一条随鼠标伸缩的虚线矩形。"""

    # 压在选中框（101）和所有标注（20/30）之上，纯粹是交互提示
    Z_VALUE = 200

    def __init__(self, scene, start_pos: QPointF):
        self._scene = scene
        self._start = QPointF(start_pos)
        pen = QPen(QColor(120, 120, 120), 1.0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self._item = RectItem(QRectF(self._start, self._start), pen)
        self._item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._item.setAcceptHoverEvents(False)
        self._item.setFlag(self._item.GraphicsItemFlag.ItemIsMovable, False)
        self._item.setFlag(self._item.GraphicsItemFlag.ItemIsSelectable, False)
        self._item.setZValue(self.Z_VALUE)
        if scene is not None:
            scene.addItem(self._item)

    def update(self, end_pos: QPointF):
        if self._item is None:
            return
        self._item.setRect(QRectF(self._start, QPointF(end_pos)).normalized())

    def clear(self):
        """把它从场景里摘掉。重复调用安全。"""
        item, self._item = self._item, None
        if item is None:
            return
        scene = item.scene()
        if scene is not None:
            scene.removeItem(item)
