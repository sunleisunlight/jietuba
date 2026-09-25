"""
截图工具栏排布对话框：拖左侧手柄调整顺序，中间设快捷键，右侧下拉框选择显示方式

对话框只负责编辑：排布与快捷键都先存在对话框内部，点「确定」后才由调用方
Toolbar._open_layout_dialog 统一写配置；点「取消」什么都不保存。

行没有做成 QListWidget 的条目再用内置拖放：InternalMove 会把被拖的条目删掉再插入，
setItemWidget 挂上去的下拉框会跟着丢失。这里每一行就是布局里的普通部件，拖动时
直接在布局里换位置。
"""

from functools import partial

from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from core import safe_event
from core.i18n import make_tr
from core.shortcut_manager import inapp_shortcut_display_text
from core.ui_scale import configure_dialog_control, dialog_scaled, dialog_scaled_f, scale_dialog_font
from settings.tool_settings import (
    ALL_TOOL_SHORTCUTS, FIXED_TOOLBAR_SHORTCUTS, SCREENSHOT_ACTION_SHORTCUTS,
    TOOLBAR_SHORTCUT_BINDINGS, ToolSettingsManager,
)
from ui.dialogs import show_confirm_dialog
from ui.fluent_lite import (
    BodyLabel, CaptionLabel, ComboBox, PrimaryPushButton, PushButton,
    SimpleCardWidget, TransparentPushButton, ui_tokens,
)
from ui.inapp_key_edit import InAppKeyEdit
from ui.toolbar_layout import (
    DEFAULT_ORDER, HIDE, LOCKED, MORE, SHOW, default_layout, normalize_layout,
)

_tr = make_tr("ToolbarLayoutDialog")

# 行标题。工具栏按钮的 tooltip 带着用法说明，放进列表太长，这里另起短名
BUTTON_NAMES = {
    "long_screenshot": "Long screenshot",
    "save": "Save",
    "screenshot_translate": "Screenshot translate",
    "text_recognize": "Recognize text",
    "scan_code": "Scan code",
    "gif": "GIF recording",
    "pen": "Pen",
    "highlighter": "Highlighter",
    "mosaic": "Mosaic",
    "spotlight": "Spotlight",
    "arrow": "Arrow",
    "number": "Number",
    "rect": "Rectangle",
    "ellipse": "Ellipse",
    "text": "Text",
    "note": "Note",
    "eraser": "Eraser",
    "undo": "Undo",
    "redo": "Redo",
    "cancel": "Cancel screenshot",
    "pin": "Pin image",
    "confirm": "Confirm",
}

MODE_NAMES = (
    (SHOW, "Always show"),
    (MORE, "In more menu"),
    (HIDE, "Always hide"),
)

_EDIT_W = 96
_EDIT_H = 28


def _external_action_labels():
    """截图作用域里没有工具栏按钮、但同样占用按键的动作显示名。

    这些名字的设置页翻译在 SettingsDialog 上下文里，这里显式指定上下文复用，
    不再为同一个动作维护第二份文案。
    """
    toolbar_keys = {cfg for cfg in TOOLBAR_SHORTCUT_BINDINGS.values() if cfg}
    labels = {}
    for cfg_key, label in SCREENSHOT_ACTION_SHORTCUTS:
        if cfg_key not in toolbar_keys:
            labels[cfg_key] = QCoreApplication.translate("SettingsDialog", label)
    for cfg_key, _tool_id, label, _default in ALL_TOOL_SHORTCUTS:
        if cfg_key not in toolbar_keys:
            labels[cfg_key] = QCoreApplication.translate("SettingsDialog", label)
    return labels


class _Grip(QWidget):
    """行首的拖动手柄（2×3 圆点）。只把按下、拖动、松开报出去，换位由对话框做。"""

    pressed = Signal()
    dragged = Signal(int)   # 鼠标的全局 y
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(dialog_scaled(16), dialog_scaled(28))
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    @safe_event
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.pressed.emit()

    @safe_event
    def mouseMoveEvent(self, event):
        # 按下后 Qt 会隐式抓住鼠标，拖出手柄、拖出对话框也照样收得到移动事件
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint().y())

    @safe_event
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.released.emit()

    @safe_event
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ui_tokens(self).text_muted))
        center = QPointF(self.rect().center())
        for dx in (-3, 3):
            for dy in (-6, 0, 6):
                painter.drawEllipse(
                    center + QPointF(dialog_scaled(dx), dialog_scaled(dy)),
                    dialog_scaled_f(1.5),
                    dialog_scaled_f(1.5),
                )
        painter.end()


class _Row(QWidget):
    """一行：拖动手柄、按钮图标、名称、快捷键、显示方式下拉框"""

    def __init__(self, key, icon, shortcut_widget, parent=None):
        super().__init__(parent)
        self.key = key
        self._dragging = False

        self.grip = _Grip(self)

        # 图标垫一块白底：工具栏图标是照着白底工具栏画的深色图标，深色主题下直接放看不清
        icon_label = QLabel(self)
        icon_label.setFixedSize(dialog_scaled(28), dialog_scaled(28))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(icon.pixmap(dialog_scaled(20), dialog_scaled(20)))
        icon_label.setStyleSheet(
            f"background: #FFFFFF; border-radius: {dialog_scaled(6)}px;"
        )

        self.shortcut_widget = shortcut_widget

        self.combo = ComboBox(self)
        configure_dialog_control(self.combo)
        for mode, text in MODE_NAMES:
            self.combo.addItem(_tr(text), mode)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            dialog_scaled(8), dialog_scaled(3),
            dialog_scaled(8), dialog_scaled(3),
        )
        layout.setSpacing(dialog_scaled(10))
        layout.addWidget(self.grip)
        layout.addWidget(icon_label)
        name_label = BodyLabel(_tr(BUTTON_NAMES[key]), self)
        configure_dialog_control(name_label)
        layout.addWidget(name_label, 1)
        layout.addWidget(shortcut_widget)
        layout.addWidget(self.combo)

    def mode(self):
        return self.combo.currentData()

    def set_mode(self, mode):
        self.combo.setCurrentIndex(self.combo.findData(mode))

    def set_dragging(self, dragging):
        """拖动中的行垫一层强调色，让用户看清自己拖的是哪一行"""
        self._dragging = dragging
        self.update()

    @safe_event
    def paintEvent(self, event):
        if not self._dragging:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ui_tokens(self).accent_soft))
        painter.drawRoundedRect(self.rect(), dialog_scaled(8), dialog_scaled(8))
        painter.end()


class ToolbarLayoutDialog(QDialog):
    """编辑截图工具栏排布与应用内快捷键。

    layout          — [(按钮, 显示方式)]
    icons           — 按钮 → QIcon
    shortcut_values — 配置键 → 当前快捷键文本（只读入，写回由调用方负责）
    """

    def __init__(self, layout, icons, shortcut_values, parent=None):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setWindowTitle(_tr("Customize Toolbar"))
        # 从全屏置顶的截图窗口里打开，和截图里的取色对话框一样置顶，免得被截图窗口盖住
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(f"QDialog {{ background: {ui_tokens(self).window}; }}")

        self._initial_values = dict(shortcut_values)
        self._shortcut_edits = {}     # 配置键 → InAppKeyEdit
        self._cleared_externals = set()  # 用户选择替换后同意清空的外部动作
        self._external_labels = _external_action_labels()

        self._card = SimpleCardWidget()
        self._list_layout = QVBoxLayout(self._card)
        self._list_layout.setContentsMargins(
            dialog_scaled(6), dialog_scaled(6),
            dialog_scaled(6), dialog_scaled(6),
        )
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)

        # 固定按钮不显示灰色禁用行；这里只为真正可调整的按钮创建界面。
        self._rows = {}
        for key in DEFAULT_ORDER:
            if key in LOCKED:
                continue
            row = _Row(key, icons[key], self._make_shortcut_widget(key), self._card)
            row.grip.pressed.connect(partial(row.set_dragging, True))
            row.grip.dragged.connect(partial(self._drag_row, row))
            row.grip.released.connect(partial(row.set_dragging, False))
            self._rows[key] = row

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._scroll.setWidget(self._card)

        hint = CaptionLabel(
            _tr("Drag the handle to reorder. Use the drop-down to change visibility."), self)
        configure_dialog_control(hint)
        shortcut_hint = CaptionLabel(
            _tr("Click a shortcut box and press a key to change it."), self)
        configure_dialog_control(shortcut_hint)

        reset_btn = TransparentPushButton(_tr("Restore defaults"), self)
        configure_dialog_control(reset_btn)
        reset_btn.clicked.connect(self._restore_defaults)
        ok_btn = PrimaryPushButton(_tr("OK"), self)
        configure_dialog_control(ok_btn)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = PushButton(_tr("Cancel"), self)
        configure_dialog_control(cancel_btn)
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            dialog_scaled(16), dialog_scaled(16),
            dialog_scaled(16), dialog_scaled(14),
        )
        root.setSpacing(dialog_scaled(10))
        root.addWidget(self._scroll, 1)
        root.addWidget(hint)
        root.addWidget(shortcut_hint)
        root.addLayout(buttons)

        self._fill(layout)
        self._fit_height_to_rows()

    # ── 快捷键编辑器 ──────────────────────────────────────

    def _make_shortcut_widget(self, key):
        """按工具栏 key 造一个快捷键控件：可配置的用 InAppKeyEdit，固定键只显示。"""
        cfg_key = TOOLBAR_SHORTCUT_BINDINGS.get(key)

        if not cfg_key:
            value = FIXED_TOOLBAR_SHORTCUTS.get(key, "—")
            label = QLabel(f"{value} ({_tr('Fixed')})", self._card)
            configure_dialog_control(label)
            label.setFixedSize(dialog_scaled(_EDIT_W), dialog_scaled(_EDIT_H))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setToolTip(_tr("Shortcut"))
            label.setStyleSheet(
                f"color: {ui_tokens(self).text_muted};"
                f"font-size: {dialog_scaled(12)}px;"
            )
            return label

        editor = InAppKeyEdit(self._card)
        editor.setFixedSize(dialog_scaled(_EDIT_W), dialog_scaled(_EDIT_H))
        editor.setToolTip(_tr("Shortcut"))
        tokens = ui_tokens(self)
        editor.setStyleSheet(
            f"InAppKeyEdit {{ border: 1px solid {tokens.border};"
            f" border-radius: {dialog_scaled(4)}px;"
            f" padding: 0px {dialog_scaled(6)}px;"
            f" background: {tokens.input_background}; color: {tokens.text}; }}"
            f"InAppKeyEdit:focus {{ border: 1px solid {tokens.accent}; }}"
        )
        # 先填值再连信号：回填时若碰上配置里遗留的重复绑定，不该弹冲突框
        editor.setText(self._initial_values.get(cfg_key, "") or "")
        editor.textChanged.connect(partial(self._on_shortcut_changed, cfg_key))
        self._shortcut_edits[cfg_key] = editor
        return editor

    def _on_shortcut_changed(self, cfg_key, text):
        """输入变化时在截图作用域内查重，冲突就询问是否替换（与设置页同一套体验）。"""
        new_text = (text or "").strip().lower()
        if not new_text or new_text.endswith("+"):
            return  # 空值或未录完的组合键

        conflict = self._find_conflict(cfg_key, new_text)
        if conflict is None:
            return
        kind, conflict_key = conflict
        editor = self._shortcut_edits[cfg_key]
        editor.blockSignals(True)
        try:
            replaced = show_confirm_dialog(
                self,
                _tr("Shortcut Conflict"),
                _tr('"%1" is already used by "%2".\nReplace it?')
                    .replace("%1", inapp_shortcut_display_text(new_text))
                    .replace("%2", self._conflict_label(kind, conflict_key)),
            )
            if replaced:
                self._clear_conflict(kind, conflict_key)
            else:
                editor.setText(self._initial_values.get(cfg_key, "") or "")
        finally:
            editor.blockSignals(False)

    def _find_conflict(self, cfg_key, new_text):
        """返回 (类型, 配置键)；没有冲突返回 None。"""
        for other_cfg, edit in self._shortcut_edits.items():
            if other_cfg != cfg_key and edit.text().strip().lower() == new_text:
                return ("row", other_cfg)
        for other_cfg, _label in self._external_labels.items():
            if other_cfg in self._cleared_externals:
                continue
            if (self._initial_values.get(other_cfg, "") or "").strip().lower() == new_text:
                return ("external", other_cfg)
        return None

    def _conflict_label(self, kind, conflict_key):
        if kind == "external":
            return self._external_labels.get(conflict_key, conflict_key)
        row = self._rows.get(self._row_key_of(conflict_key))
        if row is not None:
            return _tr(BUTTON_NAMES[row.key])
        return self._external_labels.get(conflict_key, conflict_key)

    def _row_key_of(self, cfg_key):
        for key, mapped in TOOLBAR_SHORTCUT_BINDINGS.items():
            if mapped == cfg_key:
                return key
        return None

    def _clear_conflict(self, kind, conflict_key):
        """替换：清空对方。行内直接改临时状态；外部动作记下来，点确定时一并清空。"""
        if kind == "external":
            self._cleared_externals.add(conflict_key)
            return
        edit = self._shortcut_edits.get(conflict_key)
        if edit is None:
            return
        edit.blockSignals(True)
        edit.setText("")
        edit.blockSignals(False)

    # ── 编辑结果 ──────────────────────────────────────────

    def entries(self):
        """编辑结果；不可调整的固定按钮按进入/重置对话框时的位置合并回来。"""
        entries = [(row.key, row.mode()) for row in self._ordered_rows()]
        for index, key in self._locked_slots:
            entries.insert(min(index, len(entries)), (key, SHOW))
        return normalize_layout(entries)

    def shortcut_entries(self):
        """快捷键编辑结果（含用户选择替换后清空的外部动作）。

        只是对话框内的临时状态，写回配置由调用方在 accept 之后统一做。
        """
        entries = {
            cfg_key: edit.text().strip()
            for cfg_key, edit in self._shortcut_edits.items()
        }
        for cfg_key in self._cleared_externals:
            entries[cfg_key] = ""
        return entries

    # ── 内部 ──────────────────────────────────────────────

    def _restore_defaults(self):
        """恢复默认：排布与可配置快捷键都回到当前版本的默认值，仍只改对话框内状态。"""
        self._fill(default_layout())
        defaults = ToolSettingsManager.APP_DEFAULT_SETTINGS
        for cfg_key, edit in self._shortcut_edits.items():
            edit.blockSignals(True)
            edit.setText(defaults.get(cfg_key, "") or "")
            edit.blockSignals(False)
        self._cleared_externals.clear()

    def _ordered_rows(self):
        items = (self._list_layout.itemAt(i) for i in range(self._list_layout.count()))
        return [item.widget() for item in items if item.widget() is not None]

    def _fill(self, layout):
        """按排布摆放各行、设置下拉框"""
        normalized = normalize_layout(layout)
        self._locked_slots = [
            (index, key) for index, (key, _mode) in enumerate(normalized) if key in LOCKED
        ]
        editable = [(key, mode) for key, mode in normalized if key not in LOCKED]
        for index, (key, mode) in enumerate(editable):
            row = self._rows[key]
            self._place(row, index)
            row.set_mode(mode)

    def _place(self, row, index):
        self._list_layout.removeWidget(row)
        self._list_layout.insertWidget(index, row)

    def _fit_height_to_rows(self):
        """优先完整展示全部可调整行；只有超过屏幕可用高度时才让列表滚动。"""
        self._list_layout.activate()
        content_height = self._list_layout.sizeHint().height() + 2
        self._scroll.setFixedHeight(content_height)

        desired_height = self.sizeHint().height()
        screen = self.parentWidget().screen() if self.parentWidget() else QApplication.primaryScreen()
        if screen is not None:
            max_height = max(dialog_scaled(360), screen.availableGeometry().height() - dialog_scaled(40))
            if desired_height > max_height:
                non_list_height = desired_height - content_height
                content_height = max(dialog_scaled(180), max_height - non_list_height)
                self._scroll.setFixedHeight(content_height)
                desired_height = non_list_height + content_height

        # 比原来宽：多了一列快捷键，太窄会把名称/快捷键/下拉框挤在一起
        self.resize(dialog_scaled(640), desired_height)

    def _drag_row(self, row, global_y):
        """被拖的行跟着鼠标换位：它该排第几，就看其余行里有几行的中线在鼠标上方"""
        y = self._card.mapFromGlobal(QPoint(0, global_y)).y()
        index = sum(
            1 for other in self._ordered_rows()
            if other is not row and other.geometry().center().y() < y
        )
        if self._list_layout.indexOf(row) != index:
            self._place(row, index)
            # 立刻按新顺序算出各行几何，下一次鼠标移动才能基于新位置判断
            self._list_layout.activate()
        # 拖到可见区域外时让滚动跟上
        self._scroll.ensureWidgetVisible(row, 0, 0)
