"""文字底色的风格预设直接摆在二级面板的颜色行上。

预设（白底黑字那 5 个"A"色块）以前藏在 BG 悬停弹层第三行，用户要求把它们放到
面板颜色区。弹层里只留底色和不透明度，预设按钮 reparent 到面板，点击行为
（apply_preset）不变。
"""
import pytest
from PySide6.QtWidgets import QPushButton

from ui.note_settings_panel import NoteSettingsPanel
from ui.text_background_control import BACKGROUND_PRESET_STYLES
from ui.text_settings_panel import TextSettingsPanel


@pytest.mark.parametrize("panel_cls", [TextSettingsPanel, NoteSettingsPanel])
def test_style_swatches_live_on_panel_not_in_bg_popup(qapp, panel_cls):
    panel = panel_cls()
    try:
        control = panel._background
        swatches = [swatch for swatch, _b, _f, _t in control.preset_swatches]
        assert len(swatches) == len(BACKGROUND_PRESET_STYLES)

        for swatch in swatches:
            # 进入面板一级布局：父控件就是面板本身
            assert swatch.parentWidget() is panel
            assert swatch.isVisible() or not panel.isVisible()  # 面板没显示时子件也不显示
            # 悬停弹层里不再含这行预设
            assert swatch not in control._popup.findChildren(QPushButton)

        # 弹层只剩"自定义 + 3 个预设底色"4 个颜色按钮，没有"A"风格块
        popup_buttons = control._popup.findChildren(QPushButton)
        assert len(popup_buttons) == 4
    finally:
        panel.deleteLater()


def test_note_panel_keeps_bg_toggle_next_to_font_size(qapp):
    """BG 开关不能跟着预设一起丢：它仍是面板上的可见控件。"""
    panel = NoteSettingsPanel()
    try:
        assert panel._background.toggle_btn.parentWidget() is panel
        assert panel.font_spin.parentWidget() is panel
    finally:
        panel.deleteLater()


def test_swatches_still_apply_preset_after_move(qapp):
    """搬位置不拆信号：点面板上的预设照样一次摆好底色 + 文字色 + 开关。"""
    panel = TextSettingsPanel()
    backgrounds = []
    colors = []
    panel.background_changed.connect(
        lambda enabled, color, opacity: backgrounds.append((enabled, color.name()))
    )
    panel.color_changed.connect(lambda color: colors.append(color.name()))
    try:
        panel.background_opacity = 120
        swatch = panel._background.preset_swatches[0][0]
        swatch.click()

        assert panel.background_enabled
        assert panel.background_color.name() == "#ffffff"
        assert panel.current_color.name() == "#000000"
        assert panel.background_opacity == 120
        assert backgrounds[-1] == (True, "#ffffff")
        assert colors[-1] == "#000000"
    finally:
        panel.deleteLater()
