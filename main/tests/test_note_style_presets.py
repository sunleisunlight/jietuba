# -*- coding: utf-8 -*-
"""备注面板的三档尺寸预设 + 面板状态落到备注上的回归测试。"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont


def _make_note(text=""):
    from canvas.items import NoteItem

    return NoteItem(
        target_rect=QRectF(100, 100, 200, 120),
        font=QFont("Helvetica", 14),
        color=QColor("#FF0000"),
        direction=NoteItem.POSITION_RIGHT,
        text=text,
    )


def test_size_preset_sets_stroke_and_font(qapp):
    from ui.note_settings_panel import SIZE_PRESETS, NoteSettingsPanel

    panel = NoteSettingsPanel()
    thin = SIZE_PRESETS[0]
    thick = SIZE_PRESETS[-1]
    panel._on_size_preset_clicked(thin[1], thin[2])
    thin_values = (panel.current_stroke_width, panel.current_font_size)
    panel._on_size_preset_clicked(thick[1], thick[2])
    thick_values = (panel.current_stroke_width, panel.current_font_size)
    assert thick_values[0] > thin_values[0]
    assert thick_values[1] > thin_values[1]
    panel.deleteLater()


def test_apply_note_style_updates_item(qapp):
    """面板状态必须真的落到备注上（线宽 + 字号）。"""
    from ui.screenshot_window import ScreenshotWindow

    note = _make_note("文字")
    ScreenshotWindow._apply_note_style(note, {"stroke_width": 9, "font_size": 40})
    assert int(round(float(note.get_stroke_width()))) == 9
    assert note.font().pointSize() == 40


def test_note_style_round_trip_keeps_one_x_settings(qapp):
    """2x 屏上面板 ↔ 备注往返必须回到原值，不能每往返一次就放大一倍。"""
    from ui.note_settings_panel import NoteSettingsPanel
    from ui.screenshot_window import ScreenshotWindow

    note = _make_note("文字")
    note.display_dpr = lambda: 2.0

    ScreenshotWindow._apply_note_style(note, {"stroke_width": 3, "font_size": 14})
    # 图元按物理像素绘制：1x 的 3 / 14 在 2x 屏上变成 6 / 28
    assert float(note.get_stroke_width()) == 6.0
    assert note.font().pointSize() == 28

    panel = NoteSettingsPanel()
    try:
        panel.set_state_from_item(note)
        state = panel.current_state()
        assert state["stroke_width"] == 3, "读回面板的线宽必须是 1x，否则会被写回设置再放大"
        assert state["font_size"] == 14
    finally:
        panel.deleteLater()

