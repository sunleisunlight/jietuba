"""任何工具下抓住选区边缘都能调整选区大小。

以前只有 cursor 工具把按下事件交给场景里的 SelectionItem，绘图工具的按下直接
起笔，压在选区边框上的那一下拖不动选区。现在 View 在分发链最前面识别边缘热区
（见 SelectionItem.edge_handle_at / canvas.gestures.SelectionEdgeResize），
绘图工具下也先调选区。
"""
import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPen
from PySide6.QtWidgets import QApplication

from canvas.items import EllipseItem, RectItem, SelectionItem, TextItem
from canvas.scene import CanvasScene
from canvas.undo import AddItemCommand
from canvas.view import CanvasView

W, H = 500, 380


@pytest.fixture
def scene_view(qapp):
    created = []

    def make(tool="rect", confirmed_rect=None):
        image = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("white"))
        scene = CanvasScene(image, QRectF(0, 0, W, H), enable_mosaic=True)
        view = CanvasView(scene)
        created.append((scene, view))
        QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.WindowActivate))
        rect = QRectF(0, 0, W, H) if confirmed_rect is None else confirmed_rect
        scene.selection_model.initialize_confirmed_rect(rect)
        scene.tool_controller.activate(tool)
        return scene, view

    yield make

    for scene, view in created:
        view.close()
        scene.deleteLater()


def _send(view, kind, pos, buttons=Qt.MouseButton.LeftButton):
    view_pos = QPointF(view.mapFromScene(pos))
    event = QMouseEvent(
        kind,
        view_pos,
        view.mapToGlobal(view_pos.toPoint()),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    if kind == QEvent.Type.MouseButtonPress:
        view.mousePressEvent(event)
    elif kind == QEvent.Type.MouseMove:
        view.mouseMoveEvent(event)
    else:
        view.mouseReleaseEvent(event)
    QApplication.processEvents()


def _drag(view, start, end, steps=4):
    _send(view, QEvent.Type.MouseButtonPress, start)
    for i in range(1, steps + 1):
        _send(view, QEvent.Type.MouseMove, start + (end - start) * (i / steps))
    _send(view, QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)


# ---------------------------------------------------------------------------
# SelectionItem.edge_handle_at 纯命中判定
# ---------------------------------------------------------------------------

def test_edge_handle_at_hits_eight_handles_and_band(scene_view):
    scene, _view = scene_view()
    item = scene.selection_item
    S = SelectionItem

    # 八个控制点本体
    assert item.edge_handle_at(QPointF(0, 0)) == S.HANDLE_TOP_LEFT
    assert item.edge_handle_at(QPointF(W / 2, 0)) == S.HANDLE_TOP
    assert item.edge_handle_at(QPointF(W, 0)) == S.HANDLE_TOP_RIGHT
    assert item.edge_handle_at(QPointF(0, H / 2)) == S.HANDLE_LEFT
    assert item.edge_handle_at(QPointF(W, H / 2)) == S.HANDLE_RIGHT
    assert item.edge_handle_at(QPointF(0, H)) == S.HANDLE_BOTTOM_LEFT
    assert item.edge_handle_at(QPointF(W / 2, H)) == S.HANDLE_BOTTOM
    assert item.edge_handle_at(QPointF(W, H)) == S.HANDLE_BOTTOM_RIGHT

    # 手柄之间那段边框：边带内、离角也远，归最近的边
    assert item.edge_handle_at(QPointF(W - 3, H / 4)) == S.HANDLE_RIGHT
    assert item.edge_handle_at(QPointF(W / 4, 3)) == S.HANDLE_TOP
    # 边框外侧几像素也算，方便抓
    assert item.edge_handle_at(QPointF(W + 3, H / 4)) == S.HANDLE_RIGHT
    # 角附近斜向归角
    assert item.edge_handle_at(QPointF(W - 3, H - 3)) == S.HANDLE_BOTTOM_RIGHT


def test_edge_handle_inside_body_and_far_outside_return_none(scene_view):
    scene, _view = scene_view()
    item = scene.selection_item
    assert item.edge_handle_at(QPointF(W / 2, H / 2)) == SelectionItem.HANDLE_NONE
    assert item.edge_handle_at(QPointF(W + 40, H / 2)) == SelectionItem.HANDLE_NONE
    assert item.edge_handle_at(QPointF(40, 40)) == SelectionItem.HANDLE_NONE


def test_edge_handle_unconfirmed_selection_returns_none(qapp):
    image = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    scene = CanvasScene(image, QRectF(0, 0, W, H), enable_mosaic=True)
    try:
        assert scene.selection_item.edge_handle_at(
            QPointF(W, H / 2)) == SelectionItem.HANDLE_NONE
    finally:
        scene.deleteLater()


def test_edge_handle_yields_to_text_on_the_border(scene_view):
    """边框上压着文字时让位于文字编辑，不能把点文字变成拖选区。"""
    scene, view = scene_view()
    font = QFont("Arial", 40)
    # 一串大字，文本框一直延伸到选区右边界内侧
    text = TextItem("AAAAAAAAAAA", QPointF(W - 260, H / 2 - 30), font, QColor("black"))
    scene.addItem(text)
    QApplication.processEvents()

    probe = QPointF(W - 2, H / 2 + 5)
    # 前提：探针确实在文字图元上
    assert any(isinstance(it, TextItem) for it in scene.items(probe))
    assert view._selection_edge_handle(probe) == SelectionItem.HANDLE_NONE


# ---------------------------------------------------------------------------
# View 集成：绘图工具下拖边缘 = 调选区，不是起笔
# ---------------------------------------------------------------------------

def test_drawing_tool_drag_right_handle_resizes_selection(scene_view):
    scene, view = scene_view("rect")
    _drag(view, QPointF(W, H / 2), QPointF(W + 40, H / 2))

    rect = scene.selection_model.rect()
    assert rect.right() == pytest.approx(W + 40)
    assert rect.left() == 0
    assert not scene.selection_model.is_dragging
    # 没有起笔画矩形：场景里除背景/选区装饰外没有 RectItem
    assert not any(isinstance(it, RectItem) for it in scene.items())


def test_drawing_tool_drag_band_between_handles_resizes_selection(scene_view):
    scene, view = scene_view("ellipse")
    # 按在边框内侧 2px 的边带上：边跟手走，右边界 = 原右边 + 总位移
    _drag(view, QPointF(W - 2, H / 4), QPointF(W + 25, H / 4))

    rect = scene.selection_model.rect()
    assert rect.right() == pytest.approx(W + 27)
    assert rect.left() == 0


def test_drawing_tool_drag_corner_moves_two_edges(scene_view):
    scene, view = scene_view("pen")
    _drag(view, QPointF(W - 2, H - 2), QPointF(W + 30, H + 20))

    rect = scene.selection_model.rect()
    assert rect.right() == pytest.approx(W + 32)
    assert rect.bottom() == pytest.approx(H + 22)
    assert (rect.left(), rect.top()) == (0, 0)


def test_drawing_tool_press_inside_selection_still_draws(scene_view):
    """内部区域不归边缘手势：绘图工具按下照常起笔，不能回归。"""
    scene, view = scene_view("rect")
    _send(view, QEvent.Type.MouseButtonPress, QPointF(W / 2, H / 2))
    try:
        assert view.selection_edge_resize.active is False
        assert view.drawing.active is True
    finally:
        _send(view, QEvent.Type.MouseButtonRelease, QPointF(W / 2, H / 2),
              Qt.MouseButton.NoButton)


def test_edge_resize_gesture_leaves_no_lingering_state(scene_view):
    scene, view = scene_view("rect")
    _drag(view, QPointF(W, H / 2), QPointF(W + 10, H / 2))
    assert view.selection_edge_resize.active is False
    assert view.selection_edge_resize.handle is None
    assert not scene.selection_model.is_dragging


def test_cursor_tool_resizes_edge_even_with_a_selected_annotation(scene_view):
    """截图场景：已有一条选中态标注时，点边缘不能被"点空白取消选择"吞掉。"""
    scene, view = scene_view("cursor")
    rect_item = RectItem(QRectF(60, 60, 140, 90), QPen(QColor("red"), 4))
    scene.addItem(rect_item)
    scene.undo_stack.push(AddItemCommand(scene, rect_item))
    view.smart_edit_controller.select_item(rect_item)
    assert view.smart_edit_controller.selected_item is rect_item

    _drag(view, QPointF(W, H / 2), QPointF(W + 15, H / 2))

    # 选区被调了，而不是只取消一次选择
    assert scene.selection_model.rect().right() == pytest.approx(W + 15)


def test_edge_band_with_shape_on_it_defers_to_the_shape(scene_view):
    """贴着边框的形状标注照常点选/起笔：边缘热区让位。"""
    scene, view = scene_view("rect")
    shape = RectItem(QRectF(W - 30, H / 2 - 10, 30, 20), QPen(QColor("blue"), 2))
    scene.addItem(shape)

    probe = QPointF(W - 2, H / 2)
    assert any(isinstance(it, RectItem) for it in scene.items(probe))
    assert view._selection_edge_handle(probe) == SelectionItem.HANDLE_NONE


def test_eraser_press_on_edge_with_annotation_still_erases(scene_view):
    scene, view = scene_view("eraser")
    ellipse = EllipseItem(
        QRectF(W - 30, H / 2 - 10, 30, 20), QPen(QColor("green"), 2))
    scene.addItem(ellipse)

    _send(view, QEvent.Type.MouseButtonPress, QPointF(W - 2, H / 2))
    try:
        assert view.selection_edge_resize.active is False
        assert view.drawing.active is True
    finally:
        _send(view, QEvent.Type.MouseButtonRelease, QPointF(W - 2, H / 2),
              Qt.MouseButton.NoButton)


# ---------------------------------------------------------------------------
# 几何与光标
# ---------------------------------------------------------------------------

def test_resize_rect_right_handle_changes_only_right():
    start = QRectF(10, 20, 100, 80)
    moved = SelectionItem.resize_rect(
        SelectionItem.HANDLE_RIGHT, start, QPointF(0, 0), QPointF(30, -50)
    )
    assert moved.right() == 140
    assert (moved.left(), moved.top(), moved.bottom()) == (10, 20, 100)


def test_cursor_for_handle_maps_eight_directions():
    S = SelectionItem
    assert S.cursor_for_handle(S.HANDLE_RIGHT).shape() == Qt.CursorShape.SizeHorCursor
    assert S.cursor_for_handle(S.HANDLE_TOP).shape() == Qt.CursorShape.SizeVerCursor
    assert S.cursor_for_handle(S.HANDLE_TOP_LEFT).shape() == Qt.CursorShape.SizeFDiagCursor
    assert S.cursor_for_handle(S.HANDLE_TOP_RIGHT).shape() == Qt.CursorShape.SizeBDiagCursor
    assert S.cursor_for_handle(S.HANDLE_BODY).shape() == Qt.CursorShape.SizeAllCursor
    assert S.cursor_for_handle(S.HANDLE_NONE).shape() == Qt.CursorShape.ArrowCursor
