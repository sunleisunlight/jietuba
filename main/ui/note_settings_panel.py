"""备注（Note）工具二级面板 —— 颜色 / 线宽 / 方向 / 字号 / 透明度。

备注是"目标框 + 箭头 + 一段文字"的组合，面板只暴露用户真正会改的那几项；箭头
造型、箭头指向、默认排版宽度、间隙这些留在设置里由 NoteTool / NoteItem 读取。

方向用四个小图标按钮表示（文本框在目标框的哪一侧）。图标是自绘的，不新增 svg
资源：它要表达的就是"框和文字的相对位置"，手写一遍比配一张看不出来是哪个方向的
静态图更省事，也不会在改配色时对不上。

面板改任何一项都只发一条 ``note_style_changed(state)``：备注的颜色、线宽、字号、
方向和透明度是同一个对象上的属性，一次只改一个、发四条信号等于让窗口推四条撤销
命令，而用户只做了一次操作。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QPushButton, QWidget,
)

from canvas.items import NoteItem
from core import safe_event
from core.i18n import make_tr
from core.logger import T, log_exception
from core.ui_scale import scaled
from tools.base import Tool

from .base_settings_panel import (
    StepperWidget, build_settings_panel_stylesheet, paint_rounded_panel,
)
from .color_picker_button import ColorPickerButton

_tr = make_tr("ArrowSettingsPanel")

# 预设色：与箭头/形状面板完全一致，六个色块在哪个面板里都在同一个位置
PRESET_COLORS = (
    "#FF0000",  # 红
    "#FFFF00",  # 黄
    "#00FF00",  # 绿
    "#0000FF",  # 蓝
    "#000000",  # 黑
    "#FFFFFF",  # 白
)

# 方向按钮的排列顺序：左右上下。图标上的"框"和"字"谁在左谁在右一眼可辨，
# 顺序本身只是习惯，不承载语义。
DIRECTION_ORDER = (
    NoteItem.POSITION_RIGHT,
    NoteItem.POSITION_LEFT,
    NoteItem.POSITION_TOP,
    NoteItem.POSITION_BOTTOM,
)

# 方向图标固定用中性墨色：它是"位置示意"不是颜色选择，跟着当前备注色走的话，
# 选浅色标注时白底按钮上的图标自己就看不见了（与序号样式条同理）。
DIRECTION_INK = QColor("#444444")

# 备注字号范围：与文字工具一致（8~144），备注里装的就是一段普通文字
FONT_SIZE_RANGE = (8, 144)


def render_direction_icon(direction: str, side: int, ratio: float = 1.0,
                          ink: QColor = None) -> QPixmap:
    """把"目标框 + 文字块"的相对位置画成一个方形图标。

    逻辑坐标一律用 0..side，最后按 ratio 只影响位图分辨率，高分屏上才不糊。
    """
    ink = QColor(ink) if ink is not None else QColor(DIRECTION_INK)
    pixels = max(1, round(int(side) * max(1.0, float(ratio))))
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = pixels / float(max(1, int(side)))
        painter.scale(scale, scale)
        _paint_direction_glyph(painter, direction, float(side), ink)
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(max(1.0, float(ratio)))
    return pixmap


def _paint_direction_glyph(painter: QPainter, direction: str, side: float, ink: QColor):
    """框是一个小方框，文字是三根短横线，两者的相对方位跟着 direction 走。"""
    margin = side * 0.10
    box_side = side * 0.40
    line_len = side * 0.34
    spacing = side * 0.16
    gap = side * 0.06

    pen = QPen(ink, max(1.0, side * 0.08))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    centered = (side - box_side) / 2.0
    if direction == NoteItem.POSITION_LEFT:
        box = QRectF(side - margin - box_side, centered, box_side, box_side)
    elif direction == NoteItem.POSITION_TOP:
        box = QRectF(centered, side - margin - box_side, box_side, box_side)
    elif direction == NoteItem.POSITION_BOTTOM:
        box = QRectF(centered, margin, box_side, box_side)
    else:  # POSITION_RIGHT
        box = QRectF(margin, centered, box_side, box_side)
    painter.drawRect(box)

    center = box.center()
    if direction in (NoteItem.POSITION_RIGHT, NoteItem.POSITION_LEFT):
        start = (box.right() + gap) if direction == NoteItem.POSITION_RIGHT else (box.left() - gap - line_len)
        for offset in (-spacing, 0.0, spacing):
            y = center.y() + offset
            painter.drawLine(QPointF(start, y), QPointF(start + line_len, y))
    else:
        start = (box.bottom() + gap) if direction == NoteItem.POSITION_BOTTOM else (box.top() - gap - 2 * spacing)
        left = center.x() - line_len / 2.0
        for offset in (0.0, spacing, 2 * spacing):
            y = start + offset
            painter.drawLine(QPointF(left, y), QPointF(left + line_len, y))


class NoteSettingsPanel(QWidget):
    """备注工具二级菜单"""

    # 与其他面板共用同一个翻译上下文：Line Width / Opacity (%) / Font Size /
    # Custom Color 这些键已经在那儿了，为面板再开一个上下文只会重复翻译
    TRANSLATION_CONTEXT = "ArrowSettingsPanel"

    # 载荷是当前面板上的全部备注样式（见 current_state）
    note_style_changed = Signal(object)

    # 基准尺寸（100% 下的实际像素）
    BASE_MARGIN_H = 9
    BASE_MARGIN_V = 7
    BASE_SPACING = 9
    BASE_SIZE_SPIN_WIDTH = 54
    BASE_OPACITY_SPIN_WIDTH = 65
    BASE_COLOR_BTN = 25
    BASE_PRESET_BTN = 22
    BASE_PRESET_RADIUS = 6
    BASE_DIRECTION_BTN = 25
    BASE_DIRECTION_ICON = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        default = self.default_state()
        self.current_color = QColor(default["color"])
        self.current_stroke_width = int(default["stroke_width"])
        self.current_opacity = float(default["opacity"])
        self.current_font_size = int(default["font_size"])
        self.current_direction = default["label_position"]

        self._init_ui()

    @safe_event
    def paintEvent(self, event):
        paint_rounded_panel(self)

    def _tr(self, text: str) -> str:
        return _tr(text)

    # ========================================================================
    # 界面
    # ========================================================================

    def _build_stylesheet(self) -> str:
        """方向按钮的选中态要能一眼看出"当前是哪个方向"，比通用样式再重一点。"""
        return build_settings_panel_stylesheet() + """
            QPushButton#noteDirection:checked {
                background-color: #cfe6fb;
                border: 1px solid #0078d7;
            }
            QPushButton#noteDirection:hover {
                border: 1px solid #bbb;
            }
        """

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setObjectName("separator")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        return line

    def _init_ui(self):
        layout = QHBoxLayout(self)

        # === 1. 颜色：自定义 + 六个预设 ===
        self.color_btn = ColorPickerButton(
            self.current_color, size=scaled(self.BASE_COLOR_BTN), show_alpha=False
        )
        self.color_btn.setToolTip(self._tr("Custom Color"))
        self.color_btn.color_changed.connect(self._on_color_picked)
        layout.addWidget(self.color_btn)

        self._preset_buttons = []
        for color_str in PRESET_COLORS:
            btn = QPushButton()
            btn.setToolTip(color_str)
            btn.clicked.connect(lambda checked=False, c=color_str: self._on_preset_color_clicked(c))
            layout.addWidget(btn)
            self._preset_buttons.append((btn, color_str))

        layout.addWidget(self._separator())

        # === 2. 线宽 + 透明度 ===
        # 线宽范围与 ArrowTool/NoteTool（未覆写 MIN/MAX_WIDTH）实际允许的一致，
        # 否则滚轮等入口能把宽度调到面板显示范围之外
        self.stroke_spin = StepperWidget(
            self.current_stroke_width, Tool.MIN_WIDTH, Tool.MAX_WIDTH
        )
        self.stroke_spin.setToolTip(self._tr("Line Width"))
        self.stroke_spin.valueChanged.connect(self._on_stroke_width_changed)
        layout.addWidget(self.stroke_spin)

        self.opacity_spin = StepperWidget(
            self._opacity_to_percent(self.current_opacity), 0, 100, "%"
        )
        self.opacity_spin.setToolTip(self._tr("Opacity (%)"))
        self.opacity_spin.valueChanged.connect(self._on_opacity_changed)
        layout.addWidget(self.opacity_spin)

        layout.addWidget(self._separator())

        # === 3. 方向：四个自绘小图标，互斥选中 ===
        self.direction_group = QButtonGroup(self)
        self.direction_group.setExclusive(True)
        self._direction_buttons = {}
        for direction in DIRECTION_ORDER:
            btn = QPushButton()
            btn.setObjectName("noteDirection")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(self._tr(NoteItem.POSITION_LABELS[direction]))
            btn.clicked.connect(lambda checked=False, d=direction: self._on_direction_clicked(d))
            self.direction_group.addButton(btn)
            layout.addWidget(btn)
            self._direction_buttons[direction] = btn

        layout.addWidget(self._separator())

        # === 4. 字号 ===
        self.font_spin = StepperWidget(self.current_font_size, *FONT_SIZE_RANGE)
        self.font_spin.setToolTip(self._tr("Font Size"))
        self.font_spin.valueChanged.connect(self._on_font_size_changed)
        layout.addWidget(self.font_spin)

        layout.addStretch()

        self._sync_direction_buttons()
        self.apply_scale()

    def apply_scale(self):
        """按当前比例重算面板尺寸。数值、颜色、方向都不动，只改显示大小。"""
        self.setStyleSheet(self._build_stylesheet())
        mh, mv = scaled(self.BASE_MARGIN_H), scaled(self.BASE_MARGIN_V)
        layout = self.layout()
        layout.setContentsMargins(mh, mv, mh, mv)
        layout.setSpacing(scaled(self.BASE_SPACING))

        self.stroke_spin.setFixedWidth(scaled(self.BASE_SIZE_SPIN_WIDTH))
        self.opacity_spin.setFixedWidth(scaled(self.BASE_OPACITY_SPIN_WIDTH))
        self.font_spin.setFixedWidth(scaled(self.BASE_SIZE_SPIN_WIDTH))

        color_btn = scaled(self.BASE_COLOR_BTN)
        self.color_btn.setFixedSize(color_btn, color_btn)

        preset = scaled(self.BASE_PRESET_BTN)
        radius = scaled(self.BASE_PRESET_RADIUS)
        for btn, color_str in self._preset_buttons:
            border_color = "#888888" if color_str == "#FFFFFF" else "#333333"
            btn.setFixedSize(preset, preset)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color_str};
                    border: 1px solid {border_color};
                    border-radius: {radius}px;
                }}
                QPushButton:hover {{
                    border: 2px solid #000;
                }}
            """)

        self._apply_direction_icon_sizes()
        self.adjustSize()
        self.update()

    def _apply_direction_icon_sizes(self):
        btn_side = scaled(self.BASE_DIRECTION_BTN)
        icon_side = scaled(self.BASE_DIRECTION_ICON)
        ratio = self.devicePixelRatioF()
        for direction, button in self._direction_buttons.items():
            button.setFixedSize(btn_side, btn_side)
            button.setIconSize(QSize(icon_side, icon_side))
            button.setIcon(QIcon(render_direction_icon(direction, icon_side, ratio)))

    # ========================================================================
    # 面板状态
    # ========================================================================

    @staticmethod
    def default_state() -> dict:
        """"现在画一条备注会画出什么"。

        取的是该工具的持久化设置（拿不到就回落到 DEFAULT_SETTINGS），不是写死的
        常量：面板上的"默认"必须和 NoteTool 新建时的取值同源，否则用户在面板里
        看到的和拖出来的对不上。
        """
        try:
            from settings import get_tool_settings_manager

            manager = get_tool_settings_manager()
            if manager is not None:
                return {
                    "color": QColor(manager.get_setting("note", "color", "#FF0000")),
                    "stroke_width": int(manager.get_setting("note", "stroke_width", 3)),
                    "opacity": float(manager.get_setting("note", "opacity", 1.0)),
                    "font_size": int(manager.get_setting("note", "font_size", 14)),
                    "label_position": NoteItem.normalize_position(
                        manager.get_setting("note", "label_position", NoteItem.DEFAULT_POSITION)
                    ),
                }
        except Exception as exc:
            log_exception(exc, T("读取备注默认设置"))
        return {
            "color": QColor("#FF0000"),
            "stroke_width": 3,
            "opacity": 1.0,
            "font_size": 14,
            "label_position": NoteItem.DEFAULT_POSITION,
        }

    def current_state(self) -> dict:
        """面板当前值，也是 note_style_changed 的载荷。"""
        return {
            "color": QColor(self.current_color),
            "stroke_width": int(self.current_stroke_width),
            "opacity": float(self.current_opacity),
            "font_size": int(self.current_font_size),
            "label_position": self.current_direction,
        }

    def _apply_state(self, state: dict):
        """把一份状态填进控件（不触发任何对外信号）。"""
        color = QColor(state.get("color", self.current_color))
        self.current_color = color
        self.color_btn.set_color(color)

        self.current_stroke_width = int(state.get("stroke_width", self.current_stroke_width))
        self.stroke_spin.blockSignals(True)
        self.stroke_spin.setValue(self.current_stroke_width)
        self.stroke_spin.blockSignals(False)

        self.current_opacity = max(0.0, min(1.0, float(state.get("opacity", self.current_opacity))))
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setValue(self._opacity_to_percent(self.current_opacity))
        self.opacity_spin.blockSignals(False)

        self.current_font_size = int(state.get("font_size", self.current_font_size))
        self.font_spin.blockSignals(True)
        self.font_spin.setValue(self.current_font_size)
        self.font_spin.blockSignals(False)

        self.current_direction = NoteItem.normalize_position(
            state.get("label_position", self.current_direction)
        )
        self._sync_direction_buttons()

    def load_from_config(self):
        """把备注工具的持久化设置回填到面板（切换工具、恢复工具态时调用）。"""
        self._apply_state(self.default_state())

    @staticmethod
    def save_to_config(state: dict):
        """把面板状态落盘。字段与 DEFAULT_SETTINGS["note"] 一一对应。"""
        try:
            from settings import get_tool_settings_manager

            manager = get_tool_settings_manager()
            if manager is None:
                return
            manager.update_settings(
                "note",
                color=QColor(state.get("color", "#FF0000")).name(),
                stroke_width=int(state.get("stroke_width", 3)),
                opacity=float(state.get("opacity", 1.0)),
                font_size=int(state.get("font_size", 14)),
                label_position=NoteItem.normalize_position(state.get("label_position")),
            )
        except Exception as exc:
            log_exception(exc, T("保存备注设置"))

    def set_state_from_item(self, item):
        """按选中的一条备注回填面板：先退回默认，再让备注上的字段覆盖它。

        先退默认是必要的——备注上只有"被显式设置过"的字段，直接沿用面板旧值会
        把上一条备注（或默认值）的残留显示成这一条的当前状态。
        """
        if item is None:
            return
        self.blockSignals(True)
        try:
            state = self.default_state()
            font = item.font()
            point_size = font.pointSize()
            if point_size <= 0:
                point_size = int(round(font.pointSizeF())) if font.pointSizeF() > 0 else state["font_size"]
            state["font_size"] = max(FONT_SIZE_RANGE[0], min(FONT_SIZE_RANGE[1], int(point_size)))

            color = item.defaultTextColor()
            if isinstance(color, QColor) and color.isValid():
                state["color"] = QColor(color)

            stroke_width = item.get_stroke_width()
            if stroke_width is not None:
                state["stroke_width"] = int(round(float(stroke_width)))

            opacity = item.get_visual_opacity()
            if opacity is not None:
                state["opacity"] = float(opacity)

            state["label_position"] = getattr(item, "direction", state["label_position"])
            self._apply_state(state)
        finally:
            self.blockSignals(False)

    def _sync_direction_buttons(self):
        button = self._direction_buttons.get(self.current_direction)
        if button is None:
            return
        for other in self._direction_buttons.values():
            other.setChecked(other is button)

    # ========================================================================
    # 对外接口（供 Toolbar 调用）
    # ========================================================================

    def set_color(self, color: QColor):
        """静默设置颜色"""
        self.current_color = QColor(color)
        self.color_btn.set_color(self.current_color)

    def set_size(self, size: int):
        """静默设置线宽"""
        low, high = Tool.MIN_WIDTH, Tool.MAX_WIDTH
        self.current_stroke_width = max(int(low), min(int(high), int(round(float(size)))))
        self.stroke_spin.blockSignals(True)
        self.stroke_spin.setValue(self.current_stroke_width)
        self.stroke_spin.blockSignals(False)

    def set_opacity(self, opacity_255: int):
        """静默设置透明度（入参是 0-255，与其他面板一致）"""
        self.current_opacity = max(0.0, min(1.0, float(opacity_255) / 255.0))
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setValue(self._opacity_to_percent(self.current_opacity))
        self.opacity_spin.blockSignals(False)

    def set_direction(self, direction: str):
        """静默设置方向"""
        self.current_direction = NoteItem.normalize_position(direction)
        self._sync_direction_buttons()

    def set_font_size(self, size: int):
        """静默设置字号"""
        low, high = FONT_SIZE_RANGE
        self.current_font_size = max(low, min(high, int(size)))
        self.font_spin.blockSignals(True)
        self.font_spin.setValue(self.current_font_size)
        self.font_spin.blockSignals(False)

    def retranslate(self):
        """语言切换后刷新提示文本。面板常驻，不刷新就得重启才跟着换语言。"""
        self.color_btn.setToolTip(self._tr("Custom Color"))
        self.stroke_spin.setToolTip(self._tr("Line Width"))
        self.opacity_spin.setToolTip(self._tr("Opacity (%)"))
        self.font_spin.setToolTip(self._tr("Font Size"))
        for direction, button in self._direction_buttons.items():
            button.setToolTip(self._tr(NoteItem.POSITION_LABELS[direction]))

    # ========================================================================
    # 内部槽
    # ========================================================================

    def _emit(self):
        if self.signalsBlocked():
            return
        self.note_style_changed.emit(self.current_state())

    def _on_color_picked(self, color: QColor):
        # 颜色选择器不带 alpha 通道（透明度由滑块单独管），这里只认 RGB
        picked = QColor(color)
        picked.setAlpha(255)
        self.current_color = picked
        self._emit()

    def _on_preset_color_clicked(self, color_str: str):
        self.current_color = QColor(color_str)
        self.color_btn.set_color(self.current_color)
        self._emit()

    def _on_stroke_width_changed(self, value: int):
        self.current_stroke_width = int(value)
        self._emit()

    def _on_opacity_changed(self, percent: int):
        self.current_opacity = self._percent_to_opacity_float(percent)
        self._emit()

    def _on_font_size_changed(self, value: int):
        self.current_font_size = int(value)
        self._emit()

    def _on_direction_clicked(self, direction: str):
        direction = NoteItem.normalize_position(direction)
        if direction == self.current_direction:
            # 点到已经选中的那个：互斥组不会把它取消选中，但这不是一次改动，
            # 不该多推一条撤销命令
            self._sync_direction_buttons()
            return
        self.current_direction = direction
        self._sync_direction_buttons()
        self._emit()

    # ------------------------------------------------------------------
    # 透明度换算
    # ------------------------------------------------------------------

    @staticmethod
    def _opacity_to_percent(opacity: float) -> int:
        return max(0, min(100, int(round(float(opacity) * 100))))

    @staticmethod
    def _percent_to_opacity_float(percent: int) -> float:
        return max(0.0, min(1.0, float(percent) / 100.0))
