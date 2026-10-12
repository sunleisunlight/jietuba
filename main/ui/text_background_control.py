"""文字底色控件：开关按钮 + 悬停弹层（颜色 / 不透明度 / 风格预设）。

文字工具的「BG」和备注工具里的同一个入口共用这一份：备注的正文就是一段普通
文字，底色能力本来就在 ``TextItem`` 上，两边没必要各写一份弹层。控件只负责
"用户选了什么"，落到哪个图元上由各自面板的信号接收方决定。

刻意不是 QWidget：开关按钮要摆进各自面板的一级布局里，弹层是独立的顶层窗口，
中间这一层没有自己的位置可摆。

色块样式（``style_preset_swatch`` / ``preset_swatch_button``）也放在这里：文字面板
的描边、阴影弹层用的是同一套色块，两个模块各存一份就会慢慢长得不一样。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from core import safe_event
from core.constants import CSS_FONT_FAMILY
from core.i18n import make_tr
from core.ui_scale import scaled

from .base_settings_panel import HoverPopup
from .color_picker_button import ColorPickerButton


_tr = make_tr("TextBackgroundControl")

# Qt 的 QWIDGETSIZE_MAX，PySide6 没导出这个常量
_WIDGET_SIZE_MAX = 16777215

# 底色、描边、阴影三个弹出层共用同一组预设色：弹层长一个样，白色在哪个里面都在同一个位置
EFFECT_PRESET_COLORS = (
    ("#FFFFFF", "White"),
    ("#000000", "Black"),
    ("#FFFF00", "Yellow"),
)

# 底色预设：底色和文字色成对给出。色块上直接写着字，看的就是"白底黑字"这个搭配本身；
# 点一下两个颜色一起换，不透明度沿用滑块上的当前值，换成什么还能继续微调。
BACKGROUND_PRESET_STYLES = (
    ("#FFFFFF", "#000000", "White background, black text"),
    ("#FFFFFF", "#FF0000", "White background, red text"),
    ("#000000", "#FFFFFF", "Black background, white text"),
    ("#000000", "#FF0000", "Black background, red text"),
    ("#FFFF00", "#000000", "Yellow background, black text"),
)


def popup_controls_qss() -> str:
    """悬停弹层里通用控件的样式（色块按钮、滑条、标签、分隔线）。

    弹出层是独立的顶层窗口，QSS 不继承面板，得各自挂一份；这里给的就是"一份"
    本身，底色弹层和文字面板的描边/阴影弹层共用同一段，观感才不会各走各的。
    """
    return f"""
        QPushButton {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: {scaled(3)}px;
            padding: 0px;
        }}
        QPushButton:hover {{
            border-color: #bbb;
        }}
        QPushButton:checked {{
            border: 2px solid #FF5A1F;
        }}
        QSlider {{
            background-color: transparent;
        }}
        QFrame#popupDivider {{
            background: #e8e8e8;
            border: none;
            min-height: 1px;
            max-height: 1px;
        }}
        QLabel {{
            color: #333;
            font-family: {CSS_FONT_FAMILY};
            font-size: {scaled(11)}px;
        }}
    """


def style_preset_swatch(button: QPushButton, color_hex: str, side: int):
    """按当前比例给预设色块定尺寸和样式（建按钮和改比例共用）"""
    button.setFixedSize(side, side)
    border_color = "#888888" if color_hex == "#FFFFFF" else "#333333"
    button.setStyleSheet(f"""
        QPushButton {{
            background-color: {color_hex};
            border: 1px solid {border_color};
            border-radius: {scaled(6)}px;
        }}
        QPushButton:hover {{
            border: 2px solid #000;
        }}
    """)


def preset_swatch_button(color_hex: str, side: int, tooltip: str) -> QPushButton:
    button = QPushButton()
    button.setToolTip(tooltip)
    style_preset_swatch(button, color_hex, side)
    return button


def style_background_swatch(
    button: QPushButton, background_hex: str, text_hex: str, side: int
):
    """底色预设色块：底是底色、字是文字色，"白底黑字"这类搭配一眼可辨。"""
    button.setFixedSize(side, side)
    border_color = "#888888" if background_hex == "#FFFFFF" else "#333333"
    button.setStyleSheet(f"""
        QPushButton {{
            background-color: {background_hex};
            color: {text_hex};
            border: 1px solid {border_color};
            border-radius: {scaled(4)}px;
            padding: 0px;
            font-size: {scaled(13)}px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            border: 2px solid #000;
        }}
    """)


def background_swatch_button(
    background_hex: str, text_hex: str, side: int, tooltip: str
) -> QPushButton:
    button = QPushButton("A")
    button.setToolTip(tooltip)
    style_background_swatch(button, background_hex, text_hex, side)
    return button


class TextBackgroundControl(QObject):
    """文字底色的「开关 + 悬停弹层」（颜色 / 不透明度 / 风格预设）。

    面板侧用法：把 ``toggle_btn`` 摆进自己的一级布局，连 ``changed`` 与
    ``text_color_requested``，并在改比例时调一次 ``apply_scale``。
    """

    # enabled, 底色（#RRGGBB，不含 alpha）, 不透明度 0-255
    changed = Signal(bool, QColor, int)
    # 用户点了风格预设：文字色也该换成这一套里的那个
    text_color_requested = Signal(QColor)

    # 基准尺寸（100% 下的实际像素）
    BASE_BTN = 25
    BASE_PRESET_BTN = 22
    BASE_POPUP_COLOR_BTN = 24
    BASE_OPACITY_LABEL_WIDTH = 36

    def __init__(self, panel: QWidget):
        super().__init__(panel)
        self._panel = panel
        self.enabled = False
        self._color = QColor("#FFFFFF")
        self._opacity = 178  # 约 70%：纯色底太抢眼，压住字反而看不清

        self.toggle_btn = QPushButton("BG", panel)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_btn.setToolTip(_tr("Text Background"))
        self.toggle_btn.toggled.connect(self._on_toggled)
        self.toggle_btn.installEventFilter(self)

        self._popup = HoverPopup(panel)
        self._popup.set_extra_stylesheet(popup_controls_qss())
        self._build_popup()
        self._popup.hide()

        self.apply_scale()
        self.update_toggle_style()

    # ------------------------------------------------------------------
    # 弹层
    # ------------------------------------------------------------------

    def _build_popup(self):
        layout = QVBoxLayout(self._popup)

        colors = QHBoxLayout()
        colors.addStretch()
        color_side = scaled(self.BASE_POPUP_COLOR_BTN)
        # 颜色和不透明度分开调（不透明度有自己的滑块），自定义色不带 alpha 通道
        self.color_btn = ColorPickerButton(
            QColor("white"), show_alpha=False, size=color_side
        )
        self.color_btn.setToolTip(_tr("Custom Background Color"))
        self.color_btn.color_changed.connect(self._on_color_picked)
        colors.addWidget(self.color_btn)
        self._color_swatches = []
        for color_hex, name in EFFECT_PRESET_COLORS:
            swatch = preset_swatch_button(color_hex, color_side, _tr(name))
            swatch.clicked.connect(
                lambda _checked=False, c=color_hex: self._on_color_picked(QColor(c))
            )
            colors.addWidget(swatch)
            self._color_swatches.append((swatch, color_hex))
        colors.addStretch()
        layout.addLayout(colors)

        divider = QFrame()
        divider.setObjectName("popupDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 255)
        self.opacity_slider.setToolTip(_tr("Background Opacity"))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider)
        self._opacity_label = QLabel()
        opacity_row.addWidget(self._opacity_label)
        layout.addLayout(opacity_row)

        # 风格预设按钮先建好不挂布局：attach_preset_swatches() 会把它们摆上
        # 面板一级颜色行，不用悬停 BG 弹层就能一键套"底色 + 文字色"。
        self.preset_swatches = []
        for background_hex, text_hex, tip in BACKGROUND_PRESET_STYLES:
            swatch = background_swatch_button(
                background_hex, text_hex, scaled(self.BASE_PRESET_BTN), _tr(tip)
            )
            swatch.clicked.connect(
                lambda _checked=False, bg=background_hex, fg=text_hex:
                    self.apply_preset(bg, fg)
            )
            self.preset_swatches.append((swatch, background_hex, text_hex, tip))

        self._fit_popup_width()

    def attach_preset_swatches(self, row_layout):
        """把 5 个风格预设色块挂到面板一级布局的颜色行上。

        只挂一次：按钮进入外部布局时 Qt 自动 reparent 到面板，BG 悬停弹层里
        从此只有底色和不透明度两件事。
        """
        for swatch, _background_hex, _text_hex, _tip in self.preset_swatches:
            row_layout.addWidget(swatch)

    def _fit_popup_width(self):
        """让顶层弹层按内容收口，而不是被 QWidget 的 200px 默认宽度撑开。"""
        self._popup.setMaximumWidth(_WIDGET_SIZE_MAX)
        self._popup.adjustSize()
        self._popup.setMaximumWidth(self._popup.sizeHint().width())

    @safe_event
    def eventFilter(self, obj, event):
        """悬停开关：开着就弹出设置层，移开就收起。"""
        if obj is self.toggle_btn:
            if event.type() == QEvent.Type.Enter and self.toggle_btn.isChecked():
                self._popup.show_beside(self._panel, self.toggle_btn)
            elif event.type() == QEvent.Type.Leave:
                self._popup.close_soon()
        return super().eventFilter(obj, event)

    def hide_popup(self):
        self._popup.hide()

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @property
    def color(self) -> QColor:
        """底色（#RRGGBB，不含 alpha）——不透明度由滑块单独管。"""
        return QColor(self._color)

    @property
    def opacity(self) -> int:
        return int(self._opacity)

    def color_with_alpha(self) -> QColor:
        color = QColor(self._color)
        color.setAlpha(int(self._opacity))
        return color

    def set_state(self, enabled: bool, color: QColor, opacity: int):
        """设置底色配置（不触发任何对外信号）。"""
        self.enabled = bool(enabled)
        self._color = QColor(color)
        self._color.setAlpha(255)
        self._opacity = int(opacity)

        self.toggle_btn.blockSignals(True)
        self.toggle_btn.setChecked(self.enabled)
        self.toggle_btn.blockSignals(False)
        self.color_btn.set_color(self._color)
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(self._opacity)
        self.opacity_slider.blockSignals(False)
        self._refresh_opacity_label()
        self.update_toggle_style()

    def set_color_silently(self, color: QColor):
        """只改颜色、不发信号（面板上的属性写入走这里）。"""
        self._color = QColor(color)
        self._color.setAlpha(255)
        self.color_btn.set_color(self._color)
        self.update_toggle_style()

    def set_enabled_silently(self, enabled: bool):
        """只改开关、不发信号（面板回填 / 测试里摆状态走这里）。"""
        self.enabled = bool(enabled)
        self.toggle_btn.blockSignals(True)
        self.toggle_btn.setChecked(self.enabled)
        self.toggle_btn.blockSignals(False)
        self.update_toggle_style()

    def set_opacity_silently(self, opacity: int):
        self._opacity = int(opacity)
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(self._opacity)
        self.opacity_slider.blockSignals(False)
        self._refresh_opacity_label()
        self.update_toggle_style()

    def apply_preset(self, background_hex: str, text_hex: str):
        """套用一套"底色 + 文字色"预设。

        不透明度沿用滑块上的当前值（默认 70%），套完底色、文字色、不透明度都还能
        继续单独调——预设只是把三个值摆到一个合适的起点，不是锁死。
        """
        self._on_color_picked(QColor(background_hex))
        if not self.enabled:
            # 点风格预设就是要用底色：顺手把开关打开，省得用户再点一下
            self.toggle_btn.setChecked(True)
        self.text_color_requested.emit(QColor(text_hex))

    def _refresh_opacity_label(self):
        percent = max(0, min(100, round(int(self._opacity) / 255 * 100)))
        self._opacity_label.setText(f"{percent}%")

    def update_toggle_style(self):
        """开关按钮自己就是一块"当前底色"的预览。"""
        if self.toggle_btn.isChecked():
            color = QColor(self._color)
            luminance = color.red() * 3 + color.green() * 6 + color.blue()
            text_color = "#000000" if luminance >= 1280 else "#ffffff"
            self.toggle_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {self._opacity});
                    color: {text_color};
                    border: 1px solid #999;
                    font-size: {scaled(12)}px;
                }}
            """)
        else:
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    border: 1px solid #ddd;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #f0f0f0;
                    border: 1px solid #bbb;
                }
            """)

    # ------------------------------------------------------------------
    # 尺寸与文案
    # ------------------------------------------------------------------

    def apply_scale(self):
        """按当前比例重算开关、弹层和里面控件的尺寸；状态与颜色不动。"""
        self.toggle_btn.setFixedSize(scaled(self.BASE_BTN), scaled(self.BASE_BTN))

        color_side = scaled(self.BASE_POPUP_COLOR_BTN)
        self.color_btn.setFixedSize(color_side, color_side)
        for swatch, color_hex in self._color_swatches:
            style_preset_swatch(swatch, color_hex, color_side)
        self._opacity_label.setFixedWidth(scaled(self.BASE_OPACITY_LABEL_WIDTH))
        preset_side = scaled(self.BASE_PRESET_BTN)
        for swatch, background_hex, text_hex, _tip in self.preset_swatches:
            style_background_swatch(swatch, background_hex, text_hex, preset_side)

        self._popup.set_extra_stylesheet(popup_controls_qss())
        self._fit_popup_width()
        self.update_toggle_style()

    def retranslate(self):
        """语言切换后刷新提示文本。"""
        self.toggle_btn.setToolTip(_tr("Text Background"))
        self.color_btn.setToolTip(_tr("Custom Background Color"))
        self.opacity_slider.setToolTip(_tr("Background Opacity"))
        for swatch, _background_hex, _text_hex, tip in self.preset_swatches:
            swatch.setToolTip(_tr(tip))

    # ------------------------------------------------------------------
    # 内部槽
    # ------------------------------------------------------------------

    def _on_toggled(self, checked: bool):
        self.enabled = bool(checked)
        self.update_toggle_style()
        self._emit_changed()

    def _on_color_picked(self, color: QColor):
        picked = QColor(color)
        picked.setAlpha(255)
        self._color = picked
        self.color_btn.set_color(picked)
        self.update_toggle_style()
        self._emit_changed()

    def _on_opacity_changed(self, value: int):
        self._opacity = int(value)
        self._refresh_opacity_label()
        self.update_toggle_style()
        self._emit_changed()

    def _emit_changed(self):
        self.changed.emit(bool(self.enabled), self.color_with_alpha(), int(self._opacity))
