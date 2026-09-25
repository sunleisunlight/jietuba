# -*- coding: utf-8 -*-
"""备注（Note）标注的行为测试。

备注是一个**复合标注**：目标框 + 箭头 + 文本框。用户看到的是"圈住一块地方，
旁边写一行说明，中间连一支箭头"——这是一条标注，不是三个图形。

因此这里最要紧的断言全部围绕"对外只有一个逻辑身份"：

- 场景里只有一个顶层图元（框和箭头是它自己的子图元）；
- 一次创建 / 一次删除 / 一次移动 / 一次改方向 = 撤销栈上的一条命令；
- 导出与钉图克隆只认这一个图元，不会拆成三份；
- 悬停命中它任何一个可见部分都会选中同一条备注。

方向（direction）说的是**文本框相对目标框的位置**（右上左下四选一），跟箭头
造型（arrow_style）是两码事。
"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage
from PySide6.QtWidgets import QWidget

from canvas.handle_editor import HandleType, LayerEditor
from canvas.items import ArrowItem, NoteItem, RectItem, TextItem


# ----------------------------------------------------------------------------
# fixtures / helpers
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
        stroke_width=3,
        opacity=1.0,
    )


@pytest.fixture
def tool(qapp):
    from tools.note import NoteTool
    return NoteTool()


def _active_scene(qapp):
    """返回 (scene, view)：focus 事件需要一个真正激活的 scene。"""
    from canvas.scene import CanvasScene
    from canvas.view import CanvasView

    scene = CanvasScene(_image(), QRectF(0, 0, 400, 300))
    view = CanvasView(scene)
    view.show()
    view.activateWindow()
    qapp.processEvents()
    assert scene.isActive(), "scene 没有激活，focus 相关的断言会静默失败"
    return scene, view


def _make_note(target_rect=(100, 100, 60, 40), direction=NoteItem.DEFAULT_POSITION,
               text="hello", fit_bounds=None, **kwargs):
    return NoteItem(
        target_rect=QRectF(*target_rect),
        font=QFont("Arial", 14),
        color=QColor("#E53935"),
        direction=direction,
        text=text,
        fit_bounds=None if fit_bounds is None else QRectF(*fit_bounds),
        **kwargs,
    )


def _add_note(scene, **kwargs):
    note = _make_note(**kwargs)
    scene.addItem(note)
    return note


def _top_level(scene):
    """场景里的顶层图元（不含 scene 自带的背景/选区层）。"""
    from canvas.items import BackgroundItem, SelectionItem
    return [
        it for it in scene.items()
        if it.parentItem() is None
        and not isinstance(it, (BackgroundItem, SelectionItem))
    ]


def _drag_tool(tool, ctx, start, end, steps=4):
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
# 1~7：创建
# ----------------------------------------------------------------------------

class TestCreation:
    def test_drag_creates_exactly_one_top_level_item(self, tool, ctx, scene):
        """松手后场景里只多出一个顶层图元——不是框、箭头、文字三个。"""
        _drag_tool(tool, ctx, (100, 100), (180, 150))

        items = _top_level(scene)
        assert len(items) == 1, f"一条备注被拆成了 {len(items)} 个顶层图元"
        assert isinstance(items[0], NoteItem)

    def test_target_rect_and_arrow_are_passive_children(self, tool, ctx, scene):
        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]

        children = note.childItems()
        target = next((c for c in children if isinstance(c, RectItem)), None)
        arrow = next((c for c in children if isinstance(c, ArrowItem)), None)
        assert target is not None, "备注缺少目标框"
        assert arrow is not None, "备注缺少箭头"
        assert target.parentItem() is note
        assert arrow.parentItem() is note

    def test_children_do_not_steal_mouse_events(self, tool, ctx, scene):
        """点框、点箭头都必须命中备注本身。"""
        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]

        for child in note.childItems():
            assert child.acceptedMouseButtons() == Qt.MouseButton.NoButton
            assert child.acceptHoverEvents() is False
            assert not (child.flags() & child.GraphicsItemFlag.ItemIsSelectable)
            assert not (child.flags() & child.GraphicsItemFlag.ItemIsMovable)

    def test_drag_rect_defines_the_target_box(self, tool, ctx, scene):
        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]

        target = note.target_rect_scene()
        assert target.width() == pytest.approx(80, abs=2)
        assert target.height() == pytest.approx(50, abs=2)

    def test_reverse_drag_is_normalized(self, tool, ctx, scene):
        _drag_tool(tool, ctx, (180, 150), (100, 100))
        note = _top_level(scene)[0]

        target = note.target_rect_scene()
        assert target.width() > 0 and target.height() > 0
        assert target.width() == pytest.approx(80, abs=2)

    def test_too_small_target_box_is_discarded(self, tool, ctx, scene, undo_stack):
        _drag_tool(tool, ctx, (100, 100), (100 + 5, 100 + 5))

        assert _top_level(scene) == []
        assert not undo_stack.canUndo()

    def test_creation_enters_edit_immediately(self, tool, ctx, scene):
        """拖完就能打字：焦点落在备注上，且通知了控制器自动选中。"""
        picked = []
        scene.item_auto_select_requested.connect(picked.append)

        _drag_tool(tool, ctx, (100, 100), (180, 150))

        note = _top_level(scene)[0]
        assert picked == [note]
        assert note.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction


# ----------------------------------------------------------------------------
# 8~11：自动布局与方向
# ----------------------------------------------------------------------------

class TestAutoLayout:
    def test_default_direction_is_right_when_there_is_room(self, tool, ctx, scene):
        _drag_tool(tool, ctx, (40, 100), (90, 140))
        note = _top_level(scene)[0]

        assert note.direction == NoteItem.POSITION_RIGHT
        assert note.text_box_scene().left() > note.target_rect_scene().right()

    def test_flips_to_left_when_the_right_side_is_full(self, tool, ctx, scene):
        """目标框贴着选区右边缘，右边一点地方都没有 → 翻到左侧。"""
        from canvas.selection_model import SelectionModel

        bounds = QRectF(0, 0, 400, 300)
        ctx.selection = SelectionModel()
        ctx.selection.initialize_confirmed_rect(bounds)

        _drag_tool(tool, ctx, (355, 100), (395, 140))
        note = _top_level(scene)[0]

        assert note.direction == NoteItem.POSITION_LEFT
        assert note.text_box_scene().right() < note.target_rect_scene().left()

    def test_shrinks_the_text_box_before_flipping(self, tool, ctx, scene):
        """右边有一点地方但不够宽 → 先缩窄文本框，方向仍然是右。"""
        from canvas.selection_model import SelectionModel

        ctx.selection = SelectionModel()
        ctx.selection.initialize_confirmed_rect(QRectF(0, 0, 400, 300))

        _drag_tool(tool, ctx, (200, 100), (300, 140))
        note = _top_level(scene)[0]

        assert note.direction == NoteItem.POSITION_RIGHT
        assert note.paragraph_width() < NoteItem.base_text_width()
        assert note.text_box_scene().right() <= 400 + 1

    def test_note_never_escapes_the_selection(self, tool, ctx, scene):
        from canvas.selection_model import SelectionModel

        bounds = QRectF(0, 0, 400, 300)
        ctx.selection = SelectionModel()
        ctx.selection.initialize_confirmed_rect(bounds)

        # 目标框几乎占满选区，四个方向都放不下
        _drag_tool(tool, ctx, (5, 5), (395, 295))
        note = _top_level(scene)[0]

        text_box = note.text_box_scene()
        assert text_box.left() >= bounds.left() - 1
        assert text_box.top() >= bounds.top() - 1

    def test_changing_direction_keeps_text_and_restyles_layout(self):
        note = _make_note(text="说明文字")
        right_x = note.pos().x()

        note.set_direction(NoteItem.POSITION_LEFT)

        assert note.direction == NoteItem.POSITION_LEFT
        assert note.toPlainText() == "说明文字", "改方向不该动文本内容"
        assert note.pos().x() < right_x, "文本框应当移到目标框左侧"

    def test_invalid_direction_falls_back_to_default(self):
        note = _make_note(direction="sideways")
        assert note.direction == NoteItem.DEFAULT_POSITION

    def test_arrow_connects_text_box_and_target(self, tool, ctx, scene):
        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]

        target = note.target_rect_scene()
        text_box = note.text_box_scene()
        # 方向 right + 箭头朝目标：文本侧锚点在文本框左边缘中点，目标侧在目标框右边缘中点
        assert note.arrow_at == NoteItem.ARROW_AT_TARGET
        start = note.mapToScene(note._arrow_start_local)
        end = note.mapToScene(note._arrow_end_local)
        assert start.x() == pytest.approx(text_box.left(), abs=2)
        assert end.x() == pytest.approx(target.right(), abs=2)
        assert start.x() > end.x(), "文本框在目标框右侧，箭头应当由文字指向左边的目标"


# ----------------------------------------------------------------------------
# 12~15：撤销语义 —— 一整条只算一次
# ----------------------------------------------------------------------------

class TestUndoIsOneStep:
    def test_committing_a_note_pushes_exactly_one_command(self, qapp):
        """拖着打完字再点别处：撤销栈上只多一条 AddItemCommand。"""
        scene, view = _active_scene(qapp)
        note = _make_note(text="")   # NoteItem 默认 provisional=True，和工具创建一致
        scene.addItem(note)

        note.setFocus()
        qapp.processEvents()
        note.setPlainText("这是备注内容")
        note.clearFocus()
        qapp.processEvents()

        assert scene.undo_stack.count() == 1, "一整条备注只该产生一条创建命令"
        scene.undo_stack.undo()
        assert note.scene() is None
        scene.undo_stack.redo()
        assert note.scene() is scene

    def test_an_empty_note_leaves_no_undo_trace(self, qapp):
        """拖完没打字就点别处：什么都没发生，不该吃掉用户后面的一次 Ctrl+Z。"""
        scene, view = _active_scene(qapp)
        note = _make_note(text="")
        scene.addItem(note)

        note.setFocus()
        qapp.processEvents()
        note.clearFocus()
        qapp.processEvents()

        assert scene.undo_stack.count() == 0
        assert note.scene() is None

    def test_deleting_a_note_is_one_command_and_takes_the_children_with_it(self, scene, undo_stack):
        from canvas.undo import RemoveItemCommand

        note = _add_note(scene, text="xxx")
        note._provisional = False
        scene.undo_stack.push_command(RemoveItemCommand(scene, note))

        assert note.scene() is None
        assert not any(isinstance(i, NoteItem) for i in scene.items())
        assert scene.undo_stack.count() == 1

        scene.undo_stack.undo()
        assert note.scene() is scene
        # 目标框、箭头作为子图元一起回来了
        assert len(note.childItems()) >= 2

    def test_a_full_note_lifecycle_needs_only_three_commands(self, scene, undo_stack):
        """创建 → 改方向 → 删除，只要三条命令，而不是九条。"""
        from canvas.undo import AddItemCommand, EditItemCommand, RemoveItemCommand

        editor = LayerEditor()
        note = _add_note(scene, text="xxx")
        note._provisional = False
        scene.undo_stack.push_command(AddItemCommand(scene, note))

        old = editor.capture_state(note)
        note.set_direction(NoteItem.POSITION_TOP)
        new = editor.capture_state(note)
        assert old != new
        scene.undo_stack.push_command(EditItemCommand(note, old, new))

        scene.undo_stack.push_command(RemoveItemCommand(scene, note))

        assert scene.undo_stack.count() == 3

        scene.undo_stack.undo()          # 撤销删除
        assert note.scene() is scene
        scene.undo_stack.undo()          # 撤销改方向
        assert note.direction == NoteItem.DEFAULT_POSITION
        scene.undo_stack.undo()          # 撤销创建
        assert note.scene() is None

    def test_capture_restore_extra_state_round_trips(self):
        note = _make_note(direction=NoteItem.POSITION_BOTTOM)
        note._provisional = False
        snapshot = note.capture_extra_state()

        note.set_direction(NoteItem.POSITION_TOP)
        note.set_paragraph_width(50)
        assert note.direction == NoteItem.POSITION_TOP

        note.restore_extra_state(snapshot)
        assert note.direction == NoteItem.POSITION_BOTTOM
        assert note.paragraph_width() == pytest.approx(snapshot["paragraph_width"], abs=1e-6)


# ----------------------------------------------------------------------------
# 16~20：导出 / 命中 / 钉图 / 面板接入
# ----------------------------------------------------------------------------

class TestSingleLogicalIdentity:
    def test_export_enumeration_returns_one_item(self, tool, ctx, scene):
        """get_drawing_items_in_rect 不能把根 + 两个子图元算成三条标注。"""
        _drag_tool(tool, ctx, (100, 100), (180, 150))

        items = scene.get_drawing_items_in_rect(QRectF(0, 0, 400, 300))
        assert len(items) == 1
        assert isinstance(items[0], NoteItem)

    def test_hit_test_ignores_the_gap_between_box_and_text(self, tool, ctx, scene):
        """框和文字之间的空白不算命中，压在下面的标注才点得着。"""
        # 用一个很高的目标框，让"框与文字之间的空白"足够大、便于取点
        _drag_tool(tool, ctx, (100, 100), (160, 220))
        note = _top_level(scene)[0]
        note.set_paragraph_width(60)
        note.set_direction(NoteItem.POSITION_RIGHT)

        target = note.target_rect_scene()
        text_box = note.text_box_scene()
        # 横向落在框与文字之间的空白里，纵向靠近目标框底部（远离箭头所在的中线）
        gap_point = QPointF((target.right() + text_box.left()) / 2.0, target.bottom() - 6)
        # shape() 用的是图元本地坐标，场景点要先映射进来
        assert not note.shape().contains(note.mapFromScene(gap_point)), \
            "框与文字之间的空白被算进了命中区"
        assert note.shape().contains(note.mapFromScene(text_box.center())), "文本框内部必须命中"

        # 目标框是空心的：只有描边那一圈算命中，内部空白仍然让给下面的标注
        local_target = note.target_rect_local()
        edge = QPointF(local_target.left(), local_target.center().y())
        assert note.shape().contains(edge), "目标框描边必须命中"

    def test_smart_edit_controller_classifies_note_before_text(self, tool, ctx, scene):
        """NoteItem 继承 TextItem，控制器必须优先把它认成 NOTE，否则面板会串。"""
        from canvas.smart_edit_controller import ItemType, SmartEditController

        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]
        controller = SmartEditController(scene)

        assert controller.get_item_type(note) == ItemType.NOTE
        assert controller.get_item_tool_id(note) == "note"

        plain = TextItem("t", QPointF(10, 10), QFont("Arial", 12), QColor("black"))
        assert controller.get_item_type(plain) == ItemType.TEXT
        assert controller.get_item_tool_id(plain) == "text"

    def test_drawable_pick_skips_child_items(self, tool, ctx, scene):
        from canvas.smart_edit_controller import SmartEditController

        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]

        picked = SmartEditController._pick_drawable_items(scene.items())
        assert note in picked
        for child in note.childItems():
            assert child not in picked, "备注的子图元混进了可编辑图元列表"

    def test_note_offers_target_corners_and_no_rotate_handle(self, tool, ctx, scene):
        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]
        editor = LayerEditor()
        editor.start_edit(note)

        kinds = {h.handle_type for h in editor.handles}
        assert HandleType.ITEM_DELETE in kinds
        assert HandleType.TEXT_WIDTH in kinds
        assert HandleType.ROTATE not in kinds, "备注不该提供旋转手柄——方向语义会说不清"

    def test_note_has_no_manual_save_state_leak(self, tool, ctx, scene):
        """样式改动（颜色/线宽/字号）不该改变整条备注的几何方向。"""
        _drag_tool(tool, ctx, (100, 100), (180, 150))
        note = _top_level(scene)[0]
        direction = note.direction

        note.set_note_color(QColor("#2196F3"))
        note.set_note_stroke_width(5)
        note.set_note_font_size(20)

        assert note.direction == direction
        assert note.note_stroke_width() == pytest.approx(5)
        assert note.font_point_size() == pytest.approx(20, abs=0.5)


# ----------------------------------------------------------------------------
# 钉图克隆
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

    def test_clone_is_still_one_whole_note(self, qapp):
        from canvas.scene import CanvasScene

        source = CanvasScene(_image(), QRectF(0, 0, 400, 300))
        src = _make_note((120, 90, 60, 40), direction=NoteItem.POSITION_LEFT, text="说明")
        src._provisional = False
        source.addItem(src)

        pin, view, parent = self._pin(qapp)
        pin.initialize_from_items([src], QPoint(0, 0))

        notes = [i for i in pin.scene.items() if isinstance(i, NoteItem)]
        assert len(notes) == 1, "钉图里备注被拆成了多份"
        clone = notes[0]
        assert clone is not src
        assert clone.direction == NoteItem.POSITION_LEFT
        assert clone.toPlainText() == "说明"
        # 框和箭头都是它的子图元，没有散落成独立的顶层图元
        assert any(isinstance(c, RectItem) for c in clone.childItems())
        assert any(isinstance(c, ArrowItem) for c in clone.childItems())
        assert all(c.parentItem() is not None for c in pin.scene.items() if isinstance(c, (RectItem, ArrowItem)))

    def test_clone_keeps_relative_geometry(self, qapp):
        from canvas.scene import CanvasScene

        source = CanvasScene(_image(), QRectF(0, 0, 400, 300))
        src = _make_note((120, 90, 60, 40), text="说明")
        src._provisional = False
        source.addItem(src)
        offset = QPoint(20, 10)

        pin, view, parent = self._pin(qapp)
        pin.initialize_from_items([src], offset)

        clone = next(i for i in pin.scene.items() if isinstance(i, NoteItem))
        assert clone.pos().x() == pytest.approx(src.pos().x() - offset.x(), abs=1)
        assert clone.pos().y() == pytest.approx(src.pos().y() - offset.y(), abs=1)
        # 目标框相对 pos 的偏移不变 → 整条一起平移，不是只有文字在动
        assert clone.target_rect_local() == src.target_rect_local()
