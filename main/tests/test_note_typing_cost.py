# -*- coding: utf-8 -*-
"""备注打字的代价：一个字符该脏多大一块地方。

备注是复合标注（目标框 + 箭头 + 文本框），但它的**包围盒必须只包住自己画出来的
文字框**。理由是 Qt 在文档每次排版变化（每敲一个字）时都会按包围盒失效一次：
挂上"整条备注的外接矩形"，每敲一个字就会把远处的目标框、横跨半屏的箭头连同它们
底下的背景一起重画一遍。

2026-10 实测（2560x1440 场景，文字框拖到右上角、目标框留在中下，即用户反馈的
那张截图的样子）：

- 修之前：一次按键脏区约 1.79 Mpx（文字框 1.13 + 箭头 0.63 + 目标框 0.03），
  手柄浮层还会再并上一块 1.3 Mpx 的外接矩形，屏幕上表现为"打字很卡、画面一帧
  一帧"；
- 修之后：0.02~0.12 Mpx，量级回到"跟一段普通文字差不多"。

这里锁四条不变量：

1. 备注自己的包围盒只在文字框里（目标框、箭头都不算）；
2. 打一个字，脏掉的总面积必须远小于整条备注的外接矩形；
3. 包围盒收窄之后，框和箭头依然点得中——它们靠自己的子图元命中，
   再还原回整条备注（见 canvas.items.composite_owner）；
4. 手柄浮层的失效区域不是"所有手柄的外接矩形"（备注的文字手柄与目标框四角
   分处屏幕两头，取外接矩形等于把那中间一大片全重绘一遍）。
"""
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QRegion
from PySide6.QtWidgets import QApplication

from canvas.handle_editor import LayerEditor
from canvas.items import NoteItem, composite_owner, is_composite_child

FAR_TEXT_DELTA = QPointF(320, -760)
CN = ("团队设置这一块一直有一个比较大的问题，它是通过导出和导入配置的，这样很麻烦。"
      "已知我们最新代码已经有一键代发，包括备份数据库到云端。")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _image(w=2560, h=1440):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    return img


@pytest.fixture
def scene_and_view(qapp):
    from canvas.scene import CanvasScene
    from canvas.view import CanvasView

    scene = CanvasScene(_image(), QRectF(0, 0, 2560, 1440))
    view = CanvasView(scene)
    view.resize(2560, 1440)
    view.show()
    qapp.processEvents()
    yield scene, view
    view.cleanup()
    view.close()


def _make_note(scene, text=CN, far_text=True):
    """造一条备注：文字框长、目标框小，两者之间隔着大半屏（箭头拉得很长）。"""
    note = NoteItem(
        target_rect=QRectF(1400, 900, 230, 90),
        font=QFont("Microsoft YaHei", 14),
        color=QColor("red"),
        text=text,
        fit_bounds=QRectF(0, 0, 2560, 1440),
        provisional=False,
    )
    scene.addItem(note)
    if far_text:
        note.move_text_by_scene(FAR_TEXT_DELTA)
    return note


def _dirty_rects_while_typing(scene, note, qapp, char="一"):
    """敲一个字符，收集这一轮场景的脏区。"""
    batches = []
    scene.changed.connect(lambda regions: batches.append(list(regions)))
    qapp.processEvents()
    batches.clear()
    note.setPlainText(note.toPlainText() + char)
    qapp.processEvents()
    return [r for batch in batches for r in batch]


# ---------------------------------------------------------------------------
# 不变量 1：包围盒只包文字框
# ---------------------------------------------------------------------------

def test_note_bounding_rect_covers_only_its_own_text(scene_and_view):
    scene, _view = scene_and_view
    note = _make_note(scene)

    bounding = note.boundingRect()
    assert note.text_hit_rect().contains(bounding), "包围盒不该超出自己的命中矩形"
    # 目标框在本地坐标里离文字框很远：它不能算进包围盒
    assert not bounding.contains(note.target_rect_local()), \
        "目标框被算进了备注的包围盒——每敲一个字都会连它一起重画"
    # 箭头同理（它正是"横跨半屏"的那一段）
    assert not bounding.contains(note._arrow_item.boundingRect()), \
        "箭头被算进了备注的包围盒"


# ---------------------------------------------------------------------------
# 不变量 2：打字只脏文字框那一块
# ---------------------------------------------------------------------------

def test_typing_into_a_note_keeps_the_dirty_region_local(scene_and_view):
    scene, view = scene_and_view
    note = _make_note(scene)
    view.smart_edit_controller.select_item(note)
    qapp = QApplication.instance()

    composite = note.hit_rect()
    composite_area = composite.width() * composite.height()

    rects = _dirty_rects_while_typing(scene, note, qapp)
    assert rects, "前置条件：敲一个字应该让场景产生脏区"

    total = sum(r.width() * r.height() for r in rects)
    assert total < composite_area * 0.8, (
        f"一个字符脏了 {total / 1e6:.2f} Mpx，整条备注才 {composite_area / 1e6:.2f} Mpx"
        f"——远处那一大块（框 + 长箭头）又被整块重画了"
    )

    # 备注自己的包围盒（Qt 每次排版变化都按它失效一次）必须一直只有文字框那么大
    note_rect = note.sceneBoundingRect()
    assert note_rect.width() * note_rect.height() < composite_area * 0.3, (
        f"备注自己的脏区是 {note_rect.width():.0f}x{note_rect.height():.0f}，"
        f"没有收窄到文字框"
    )


def test_typing_does_not_rebuild_the_arrow_when_its_anchor_stays_put(scene_and_view):
    """文字变高、但箭头端点还贴在文字框没动过的那条边上时，箭头不该被重算。

    重算一次 = 重建一遍箭头路径（几十个点的并集/描边）再整块重画它的包围盒，
    而它可能有半屏那么长。
    """
    scene, view = scene_and_view
    # 方向右：文字框贴目标框右侧，端点落在文字框左边（不会随高度移动的边）
    note = _make_note(scene, far_text=False)
    note.set_direction(NoteItem.POSITION_RIGHT)
    view.smart_edit_controller.select_item(note)

    calls = []
    original = note._arrow_item.set_positions

    def spy(start, end):
        calls.append((start, end))
        return original(start, end)

    note._arrow_item.set_positions = spy
    note.setPlainText(note.toPlainText() + "一")
    QApplication.instance().processEvents()

    assert not calls, f"文字只长高了一点，箭头却被重新摆了 {len(calls)} 次"


# ---------------------------------------------------------------------------
# 不变量 3：框和箭头仍然点得中
# ---------------------------------------------------------------------------

def test_target_box_and_arrow_are_still_picked_as_the_note(scene_and_view):
    from canvas.smart_edit_controller import SmartEditController

    scene, _view = scene_and_view
    note = _make_note(scene)

    target = note.target_rect_scene()
    arrow = note.mapToScene((note._arrow_start_local + note._arrow_end_local) / 2.0)

    for label, point in (
        ("目标框描边", QPointF(target.left(), target.center().y())),
        ("箭头中段", arrow),
    ):
        picked = SmartEditController._pick_drawable_items(scene.items(point))
        assert note in picked, f"点在{label}上没能选中这条备注"


def test_composite_children_point_back_at_their_note(scene_and_view):
    scene, _view = scene_and_view
    note = _make_note(scene)

    for child in note.childItems():
        assert is_composite_child(child)
        assert composite_owner(child) is note


# ---------------------------------------------------------------------------
# 不变量 4：手柄浮层不按外接矩形失效
# ---------------------------------------------------------------------------

def _region_area(region) -> int:
    """区域的真实面积（逐个矩形相加，不是外接矩形）。"""
    return sum(rect.width() * rect.height() for rect in region)


def test_handle_overlay_does_not_invalidate_the_handles_bounding_box(scene_and_view):
    """浮层的失效区域必须按单个手柄的小方块取，不能退化成它们的外接矩形。

    备注的文字手柄在文字框上、目标框四角在屏幕另一头，外接矩形会把中间那一大片
    空白圈进来；浮层是半透明的，失效到哪就会把底下的内容层在同一块地方重绘到哪。
    """
    scene, view = scene_and_view
    note = _make_note(scene)
    view.smart_edit_controller.select_item(note)
    QApplication.instance().processEvents()

    editor = view.smart_edit_controller.layer_editor
    assert isinstance(editor, LayerEditor) and editor.is_editing()

    handle_rects = editor.handle_rects()
    assert len(handle_rects) >= 5, "前置条件：备注应同时有文字手柄和目标框四角"

    bounds = QRectF()
    for rect in handle_rects:
        bounds = bounds.united(rect)

    region = view._handle_overlay._handles_viewport_region()
    assert not region.isEmpty()

    handle_pixels = 0
    for rect in handle_rects:
        mapped = view.viewportTransform().mapRect(rect).toAlignedRect()
        handle_pixels += (mapped.width() + 6) * (mapped.height() + 6)

    bbox_area = bounds.width() * bounds.height()
    area = _region_area(region)
    assert area < bbox_area * 0.2, (
        "浮层失效区域退回了手柄的外接矩形："
        f"外接矩形 {bounds.width():.0f}x{bounds.height():.0f}（{bbox_area / 1e6:.2f} Mpx），"
        f"实际失效面积 {area / 1e6:.3f} Mpx"
    )
    assert area < handle_pixels * 4, "浮层失效范围远大于手柄本身占的像素"
