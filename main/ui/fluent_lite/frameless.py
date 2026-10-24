"""Shared frameless window foundation for application dialogs."""

from PySide6.QtCore import Qt
from qframelesswindow import FramelessDialog

from core.ui_theme import get_ui_theme

from .theme import paint_solid_background


class FrostedFramelessDialog(FramelessDialog):
    """Frameless dialog with one consistent opaque solid background.

    The previous acrylic/blur detection has been removed in favour of a cheap,
    stable solid backdrop (see ``paint_solid_background``).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._frosted_corner_radius = 8
        get_ui_theme().theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _tokens):
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        # macOS：qframelesswindow 只在初始化时隐藏原生红绿灯，窗口真正显示后
        # AppKit 会把它们放回来。这里显式声明使用原生按钮——既保证一定有关闭/
        # 缩放入口，也不会和标题栏里另画的一组叠成"两套按钮"。
        # 只有 macOS 的 FramelessDialog 才有这个方法，Windows 上 getattr 取不到。
        set_visible = getattr(self, "setSystemTitleBarButtonVisible", None)
        if callable(set_visible):
            set_visible(True)

    def paintEvent(self, event):
        paint_solid_background(self, self._frosted_corner_radius)


__all__ = ["FramelessDialog", "FrostedFramelessDialog"]
