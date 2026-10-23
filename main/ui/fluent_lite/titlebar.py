"""Shared Fluent title bar for the application's standalone windows."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget
from qframelesswindow import TitleBar, TitleBarButton
from qframelesswindow.utils import toggleMaxState

import sys

from core.ui_scale import widget_scaled as _px
from core.ui_theme import get_ui_theme

from .theme import FONT_FAMILY, ui_tokens


class _FluentCaptionButton(TitleBarButton):
    """Scale-aware caption button shared by every Fluent window."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    CLOSE = "close"

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._is_maximized = False

    def setMaxState(self, is_maximized):
        is_maximized = bool(is_maximized)
        if self._is_maximized == is_maximized:
            return
        self._is_maximized = is_maximized
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color, background = self._getColors()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRect(self.rect())

        # The upstream qframelesswindow glyphs use fixed 46 x 32 coordinates.
        # Derive all geometry from this button instead so application scaling
        # cannot pull the mark away from its visual centre.
        factor = self.width() / 46.0
        icon_side = 10.0 * factor
        center = QRectF(self.rect()).center()
        left = center.x() - icon_side / 2.0
        top = center.y() - icon_side / 2.0

        pen = QPen(color, max(1.0, factor))
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.kind == self.MINIMIZE:
            y = center.y() + 2.0 * factor
            painter.drawLine(QPointF(left, y), QPointF(left + icon_side, y))
        elif self.kind == self.CLOSE:
            painter.drawLine(
                QPointF(left, top), QPointF(left + icon_side, top + icon_side)
            )
            painter.drawLine(
                QPointF(left + icon_side, top), QPointF(left, top + icon_side)
            )
        elif not self._is_maximized:
            painter.drawRect(QRectF(left, top, icon_side, icon_side))
        else:
            offset = 2.0 * factor
            restore_side = icon_side - offset
            painter.drawRect(QRectF(left, top + offset, restore_side, restore_side))
            painter.drawRect(QRectF(left + offset, top, restore_side, restore_side))


class _MacTrafficLights(QWidget):
    """macOS 原生风格的红黄绿窗口按钮，固定在标题栏左上角。

    窗口是自绘无边框的，拿不到 AppKit 的真按钮，所以按 macOS 的度量自绘：
    直径 12pt、间距 8pt。行为与原生一致：红=关闭，黄=最小化，绿=缩放。
    """

    CLOSE_COLOR = "#FF5F57"
    MINIMIZE_COLOR = "#FEBC2E"
    ZOOM_COLOR = "#28C840"
    DIAMETER = 12
    GAP = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._resize_to_metrics()

    def _resize_to_metrics(self):
        d = _px(self, self.DIAMETER)
        gap = _px(self, self.GAP)
        self.setFixedSize(d * 3 + gap * 2, max(d, _px(self, 14)))

    def _circle_rect(self, index: int) -> QRectF:
        d = float(_px(self, self.DIAMETER))
        gap = float(_px(self, self.GAP))
        x = index * (d + gap)
        return QRectF(x, (self.height() - d) / 2.0, d, d)

    def _index_at(self, x: float) -> int:
        d = float(_px(self, self.DIAMETER))
        gap = float(_px(self, self.GAP))
        if x < 0:
            return -1
        for i in range(3):
            left = i * (d + gap)
            if left <= x <= left + d:
                return i
        return -1

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        colors = (self.CLOSE_COLOR, self.MINIMIZE_COLOR, self.ZOOM_COLOR)
        for i, color in enumerate(colors):
            rect = self._circle_rect(i)
            painter.setBrush(QColor(color))
            painter.drawEllipse(rect)
            if self._hovered:
                self._paint_glyph(painter, i, rect)

    def _paint_glyph(self, painter: QPainter, index: int, rect: QRectF):
        """悬停时画出原生按钮里的 × / − / ⤢ 符号。"""
        d = rect.width()
        inset = d * 0.3
        pen = QPen(QColor(60, 40, 20, 150), max(1.0, d * 0.12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inner = rect.adjusted(inset, inset, -inset, -inset)
        if index == 0:
            painter.drawLine(inner.topLeft(), inner.bottomRight())
            painter.drawLine(inner.topRight(), inner.bottomLeft())
        elif index == 1:
            y = rect.center().y()
            painter.drawLine(QPointF(inner.left(), y), QPointF(inner.right(), y))
        else:
            # 缩放按钮用两个对角小三角示意，避免依赖字体符号
            half = inner.width() / 2.0
            left = QPointF(inner.left(), inner.bottom())
            top = QPointF(inner.left(), inner.top())
            corner = QPointF(inner.left() + half, inner.top() + half)
            painter.setBrush(QColor(60, 40, 20, 120))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon([left, top, corner])
            right = QPointF(inner.right(), inner.top())
            bottom = QPointF(inner.right(), inner.bottom())
            corner2 = QPointF(inner.right() - half, inner.bottom() - half)
            painter.drawPolygon([right, bottom, corner2])

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(event.position().x())
            window = self.window()
            if index == 0:
                window.close()
            elif index == 1:
                window.showMinimized()
            elif index == 2:
                toggleMaxState(window)
        super().mouseReleaseEvent(event)


class FluentTitleBar(TitleBar):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("fluentTitleBar")

        # Replace qframelesswindow's fixed-coordinate glyphs once here rather
        # than letting individual windows implement their own caption buttons.
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            self.hBoxLayout.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.minBtn = _FluentCaptionButton(_FluentCaptionButton.MINIMIZE, self)
        self.maxBtn = _FluentCaptionButton(_FluentCaptionButton.MAXIMIZE, self)
        self.closeBtn = _FluentCaptionButton(_FluentCaptionButton.CLOSE, self)
        self.minBtn.clicked.connect(self.window().showMinimized)
        self.maxBtn.clicked.connect(lambda: toggleMaxState(self.window()))
        self.closeBtn.clicked.connect(self.window().close)

        # macOS 的原生窗口按钮在标题栏左上角（红黄绿），不是 Windows 右上角的
        # ×−□。这里按平台二选一，避免在 Mac 上画出"这是 Windows 才会出现的×"。
        self._is_mac = sys.platform == "darwin"
        if self._is_mac:
            for button in (self.minBtn, self.maxBtn, self.closeBtn):
                button.hide()
            self.trafficLights = _MacTrafficLights(self)
        else:
            self.hBoxLayout.addWidget(self.minBtn)
            self.hBoxLayout.addWidget(self.maxBtn)
            self.hBoxLayout.addWidget(self.closeBtn)

        self.setFixedHeight(32)
        self.buttonLayout = self.hBoxLayout
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(22, 22)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.titleLabel = QLabel(parent.windowTitle(), self)
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)
        if self._is_mac:
            self.hBoxLayout.insertWidget(
                0, self.trafficLights, 0, Qt.AlignmentFlag.AlignVCenter
            )
            # 红黄绿占住左上角，标题文字必须让出这段距离，否则会压在一起
            self.hBoxLayout.insertWidget(1, self.iconLabel)
            self.hBoxLayout.insertWidget(2, self.titleLabel)
            self.hBoxLayout.setContentsMargins(_px(self, 12), 0, _px(self, 12), 0)
            self.hBoxLayout.setSpacing(_px(self, 12))
        else:
            self.hBoxLayout.insertWidget(0, self.iconLabel)
            self.hBoxLayout.insertWidget(1, self.titleLabel)
        parent.windowTitleChanged.connect(self.setTitle)
        parent.windowIconChanged.connect(self.setIcon)
        # Scope transparency to the title-bar container.  An unqualified
        # declaration cascades to child widgets and erases backgrounds such as
        # the translation window's logo, status badge and checked pin button.
        self.setStyleSheet(
            "QWidget#fluentTitleBar { background: transparent; }"
        )

    def _apply_theme(self, _tokens=None):
        tokens = ui_tokens(self)
        self.setFixedHeight(_px(self, 32))
        self.iconLabel.setFixedSize(_px(self, 22), _px(self, 22))
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            button.setFixedSize(_px(self, 46), _px(self, 32))
        self.titleLabel.setStyleSheet(
            f"color: {tokens.text}; font: {_px(self, 12)}px {FONT_FAMILY}; "
            "background: transparent;"
        )
        traffic = getattr(self, "trafficLights", None)
        if traffic is not None:
            traffic._resize_to_metrics()
        self._apply_caption_colors()

    def _apply_caption_colors(self):
        """Caption-button colours, as a single overridable source.

        Windows with a palette of their own override this rather than
        re-colouring the buttons from outside: _apply_theme is connected to
        theme_changed, so anything applied from outside is painted back over.
        Overrides run before the subclass constructor finishes, so they must
        not depend on state that constructor sets up.
        """
        tokens = ui_tokens(self)
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            button.setNormalColor(QColor(tokens.text_muted))
            button.setHoverColor(QColor(tokens.text))
            button.setPressedColor(QColor(tokens.text))
            button.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            button.setHoverBackgroundColor(QColor(tokens.surface_hover))
            button.setPressedBackgroundColor(QColor(tokens.accent_soft))
        self.closeBtn.setHoverColor(QColor("#FFFFFF"))
        self.closeBtn.setHoverBackgroundColor(QColor("#C42B1C"))

    def setTitle(self, title):
        self.titleLabel.setText(str(title))

    def setIcon(self, icon):
        side = _px(self, 16)
        self.iconLabel.setPixmap(icon.pixmap(side, side))
