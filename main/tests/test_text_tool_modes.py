# -*- coding: utf-8 -*-
"""文字工具的双模式（Photoshop 式）行为测试。

历史问题：``TextItem.__init__`` 直接把 ``setTextWidth(-1)`` 定死，文字宽度永远
不受限、也永远不会自动换行；``TextTool.on_press`` 按下即创建图元，根本没有拖拽
状态机。于是"拖一个框出来写一段段落文字"这件事在工具层无法表达。

现在两种模式并存，且由**明确的字段**区分而不是靠 ``textWidth()`` 反推：

- 单击 → 点文本：``paragraph_width is None``，``setTextWidth(-1)``，宽度随内容增长；
- 拖拽 → 段落文本：``paragraph_width`` 有值，``setTextWidth(width)``，右边界自动换行。

这里覆盖 A~G 七件事：click / drag / reverse drag / auto wrap / resize width /
pin clone / point text regression。
"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage
from PySide6.QtWidgets import QWidget

from canvas.handle_editor import HandleType, LayerEditor
from canvas.items import TextItem
from tools.text import TextTool


# ----------------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------------

def _image(w=400, h=300):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    return img


@pytest.fixture
def scene(qapp):
    from canvas.scene import CanvasScene
    return CanvasScene(_image(), QRectF(0, 0, 400, 300))


@pytest.fixture
def undo_stack(qapp):
    from canvas.undo import CommandUndoStack
    return CommandUndoStack()


@pytest.fixture
def ctx(scene, undo_stack):
    from tools.base import ToolContext
    from canvas.selection_model import SelectionModel
    return ToolContext(
        scene=scene,
        selection=SelectionModel(),
        undo_stack=undo_stack,
        color=QColor("#FF0000"),
        stroke_width=4,
        opacity=1.0,
    )


@pytest.fixture
def tool(qapp):
    from tools.text import TextTool
    return TextTool()


def _text_items(scene):
    """场景里的顶层文字图元（排除场景背景/选区，也排除复合标注的子图元）。"""
    return [
        it for it in scene.items()
        if isinstance(it, TextItem) and it.parentItem() is None
    ]


def _only_text(scene) -> TextItem:
    items = _text_items(scene)
    assert len(items) == 1, f"期望恰好一段文字，实际 {len(items)} 个"
    return items[0]


def _click(tool, ctx, pos):
    tool.on_press(QPointF(*pos), Qt.MouseButton.LeftButton, ctx)
    tool.on_release(QPointF(*pos), ctx)


def _drag(tool, ctx, start, end, steps=4):
    tool.on_press(QPointF(*start), Qt.MouseButton.LeftButton, ctx)
    for i in range(1, steps + 1):
        t = i / steps
        tool.on_move(
            QPointF(start[0] + (end[0] - start[0]) * t,
                    start[1] + (end[1] - start[1]) * t),
            ctx,
        )
    tool.on_release(QPointF(*end), ctx)


# ----------------------------------------------------------------------------
# A. 单击 = 点文本
# ----------------------------------------------------------------------------

class TestClickCreatesPointText:
    def test_click_creates_a_single_point_text(self, tool, ctx, scene):
        _click(tool, ctx, (60, 60))

        item = _only_text(scene)
        assert isinstance(item, TextItem)
        assert item.is_paragraph_text() is False, "单击不该产生段落文本"
        assert item.paragraph_width() is None
        assert item.textWidth() < 0, "点文本的 textWidth 必须是 -1（宽度随内容增长）"

    def test_click_lands_at_the_press_point(self, tool, ctx, scene):
        _click(tool, ctx, (60, 70))

        item = _only_text(scene)
        assert item.pos().x() == pytest.approx(60, abs=1)
        assert item.pos().y() == pytest.approx(70, abs=1)

    def test_click_enters_edit_immediately(self, tool, ctx, scene):
        """松手即可打字：光标落在图元上。"""
        _click(tool, ctx, (60, 60))

        item = _only_text(scene)
        assert item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction


# ----------------------------------------------------------------------------
# B. 拖拽 = 段落文本
# ----------------------------------------------------------------------------

class TestDragCreatesParagraphText:
    def test_drag_creates_paragraph_text_with_the_dragged_width(self, tool, ctx, scene):
        _drag(tool, ctx, (40, 40), (200, 120))

        item = _only_text(scene)
        assert item.is_paragraph_text() is True
        assert item.paragraph_width() == pytest.approx(160, abs=2)
        assert item.textWidth() == pytest.approx(160, abs=2)

    def test_paragraph_item_starts_at_the_drag_origin(self, tool, ctx, scene):
        _drag(tool, ctx, (40, 40), (200, 120))

        item = _only_text(scene)
        assert item.pos().x() == pytest.approx(40, abs=2)
        assert item.pos().y() == pytest.approx(40, abs=2)

    def test_a_tiny_jitter_is_treated_as_a_click(self, tool, ctx, scene):
        """抖了一两个像素的"拖拽"其实是单击，不该凭空冒出一个最窄的段落框。"""
        _drag(tool, ctx, (60, 60), (60 + TextTool.DRAG_THRESHOLD - 1, 60), steps=2)

        item = _only_text(scene)
        assert item.is_paragraph_text() is False

    def test_a_very_narrow_drag_is_clamped_to_the_minimum(self, tool, ctx, scene):
        """拖得比最小栏宽还窄时，set_paragraph_width 会兜底到最小宽度。"""
        _drag(tool, ctx, (60, 60), (60 + TextTool.DRAG_THRESHOLD + 1, 160), steps=3)

        item = _only_text(scene)
        assert item.is_paragraph_text() is True
        assert item.paragraph_width() >= TextItem.min_paragraph_width() - 1e-6


# ----------------------------------------------------------------------------
# C. 反向拖拽仍然得到规范化矩形
# ----------------------------------------------------------------------------

class TestReverseDrag:
    def test_dragging_backwards_yields_a_normalized_paragraph(self, tool, ctx, scene):
        _drag(tool, ctx, (200, 120), (40, 40))

        item = _only_text(scene)
        assert item.is_paragraph_text() is True
        assert item.paragraph_width() > 0
        assert item.paragraph_width() == pytest.approx(160, abs=2)
        # 起点（左上）是拖拽的终点，而不是按下点
        assert item.pos().x() == pytest.approx(40, abs=2)
        assert item.pos().y() == pytest.approx(40, abs=2)


# ----------------------------------------------------------------------------
# D. 自动换行 / 纵向自增长
# ----------------------------------------------------------------------------

LONG_TEXT = "The quick brown fox jumps over the lazy dog and keeps running " * 3


class TestAutoWrap:
    def test_paragraph_text_wraps_at_the_right_edge(self, tool, ctx, scene):
        _drag(tool, ctx, (20, 20), (140, 120))
        item = _only_text(scene)
        item.setFont(QFont("Arial", 14))
        width = item.paragraph_width()

        item.setPlainText(LONG_TEXT)

        # 同样的文字在点文本下是一条横贯全屏的长带，段落文本必须被限制在栏宽内
        point = TextItem(LONG_TEXT, QPointF(0, 0), QFont("Arial", 14), QColor("black"))
        assert point.document_rect().width() > width, "用例前提不成立：文字本身没超宽"
        assert item.document_rect().width() <= width + 16

    def test_more_text_grows_the_box_vertically(self, tool, ctx, scene):
        _drag(tool, ctx, (20, 20), (140, 120))
        item = _only_text(scene)
        item.setFont(QFont("Arial", 14))

        item.setPlainText("short")
        short_height = item.document_rect().height()

        item.setPlainText(LONG_TEXT)
        long_height = item.document_rect().height()

        assert long_height > short_height, "内容变多，段落文本框应当向下自然增高"

    def test_point_text_never_wraps(self, tool, ctx, scene):
        """点文本回归：宽度随内容增长，绝不自动换行。"""
        _click(tool, ctx, (20, 20))
        item = _only_text(scene)
        item.setFont(QFont("Arial", 14))

        item.setPlainText("short")
        short_width = item.document_rect().width()
        item.setPlainText(LONG_TEXT)
        long_width = item.document_rect().width()

        assert long_width > short_width
        assert item.textWidth() < 0


# ----------------------------------------------------------------------------
# E. 右边中点手柄调整排版宽度
# ----------------------------------------------------------------------------

def _text_width_handle(editor):
    handle = next(
        (h for h in editor.handles if h.handle_type == HandleType.TEXT_WIDTH), None
    )
    assert handle is not None, "段落文本必须提供 TEXT_WIDTH 手柄"
    return handle


class TestResizeWidthHandle:
    def test_dragging_the_handle_changes_only_the_layout_width(self, tool, ctx, scene):
        _drag(tool, ctx, (20, 20), (180, 120))
        item = _only_text(scene)
        item.setFont(QFont("Arial", 14))
        item.setPlainText(LONG_TEXT)
        font_size_before = item.font_point_size()

        editor = LayerEditor()
        editor.start_edit(item)
        handle = _text_width_handle(editor)
        start = QPointF(handle.position)
        # 往左拖 40px：宽度变窄，左侧锚点不动
        left_before = item.pos()
        editor.start_drag(handle, start)
        editor.drag_to(QPointF(start.x() - 40, start.y()))
        editor.end_drag()

        assert item.paragraph_width() == pytest.approx(160 - 40, abs=2)
        assert item.font_point_size() == pytest.approx(font_size_before, abs=1e-6), "改宽度不该动字号"
        assert item.pos() == left_before, "缩窄时左侧锚点必须保持稳定"

    def test_width_drag_reflows_the_text_immediately(self, tool, ctx, scene):
        _drag(tool, ctx, (20, 20), (200, 120))
        item = _only_text(scene)
        item.setFont(QFont("Arial", 14))
        item.setPlainText(LONG_TEXT)
        wide_height = item.document_rect().height()

        editor = LayerEditor()
        editor.start_edit(item)
        handle = _text_width_handle(editor)
        start = QPointF(handle.position)
        editor.start_drag(handle, start)
        editor.drag_to(QPointF(start.x() - 100, start.y()))
        editor.end_drag()

        assert item.document_rect().height() > wide_height, "栏宽变窄后文字应当重新折行、变高"

    def test_one_drag_produces_exactly_one_undo_step(self, tool, ctx, scene, undo_stack):
        """拖宽度的过程中每一帧都会调 drag_to，但撤销栈上只能留一条命令。"""
        _drag(tool, ctx, (20, 20), (200, 120))
        item = _only_text(scene)
        item.setPlainText("hello")
        item.clearFocus()
        base_count = undo_stack.count()

        editor = LayerEditor()
        editor.start_edit(item)
        handle = _text_width_handle(editor)
        start = QPointF(handle.position)
        editor.start_drag(handle, start)
        for dx in (5, 10, 20, 40, 60):
            editor.drag_to(QPointF(start.x() + dx, start.y()))
        editor.end_drag(undo_stack)

        assert undo_stack.count() == base_count + 1, "一次拖拽只能产生一个 Undo step"

    def test_undo_restores_the_previous_width(self, tool, ctx, scene, undo_stack):
        _drag(tool, ctx, (20, 20), (200, 120))
        item = _only_text(scene)
        item.setFont(QFont("Arial", 14))
        item.setPlainText(LONG_TEXT)
        original = item.paragraph_width()

        editor = LayerEditor()
        editor.start_edit(item)
        handle = _text_width_handle(editor)
        start = QPointF(handle.position)
        editor.start_drag(handle, start)
        editor.drag_to(QPointF(start.x() - 60, start.y()))
        editor.end_drag(undo_stack)
        assert item.paragraph_width() == pytest.approx(original - 60, abs=2)

        undo_stack.undo()
        assert item.paragraph_width() == pytest.approx(original, abs=2)

        undo_stack.redo()
        assert item.paragraph_width() == pytest.approx(original - 60, abs=2)

    def test_point_text_offers_no_width_handle(self, tool, ctx, scene):
        _click(tool, ctx, (20, 20))
        item = _only_text(scene)

        editor = LayerEditor()
        editor.start_edit(item)
        assert all(h.handle_type != HandleType.TEXT_WIDTH for h in editor.handles)


# ----------------------------------------------------------------------------
# F. 钉图克隆保留段落宽度
# ----------------------------------------------------------------------------

class TestPinClone:
    def _pin(self, qapp):
        from pin.pin_canvas import PinCanvas
        from canvas.view import CanvasView

        parent = QWidget()
        parent._is_editing = False
        parent.toolbar = None
        pin = PinCanvas(parent, QSize(400, 300), _image())
        view = CanvasView(pin.scene)
        view.show()
        view.activateWindow()
        qapp.processEvents()
        return pin, view, parent

    def test_paragraph_text_clone_keeps_its_layout_width(self, qapp):
        from canvas.scene import CanvasScene

        source_scene = CanvasScene(_image(), QRectF(0, 0, 400, 300))
        src = TextItem("hello world", QPointF(20, 20), QFont("Arial", 14), QColor("black"))
        src.set_paragraph_width(150)
        source_scene.addItem(src)

        pin, view, parent = self._pin(qapp)
        pin.initialize_from_items([src], QPoint(0, 0))

        cloned = next(i for i in pin.scene.items() if isinstance(i, TextItem))
        assert cloned.is_paragraph_text() is True, "克隆后退化成了点文本"
        assert cloned.paragraph_width() == pytest.approx(src.paragraph_width(), abs=2)
        assert cloned.textWidth() >= 0

    def test_point_text_clone_stays_point_text(self, qapp):
        from canvas.scene import CanvasScene

        source_scene = CanvasScene(_image(), QRectF(0, 0, 400, 300))
        src = TextItem("hello", QPointF(20, 20), QFont("Arial", 14), QColor("black"))
        source_scene.addItem(src)

        pin, view, parent = self._pin(qapp)
        pin.initialize_from_items([src], QPoint(0, 0))

        cloned = next(i for i in pin.scene.items() if isinstance(i, TextItem))
        assert cloned.is_paragraph_text() is False
        assert cloned.textWidth() < 0
