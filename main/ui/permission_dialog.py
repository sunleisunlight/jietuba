# -*- coding: utf-8 -*-
"""macOS 风格的权限引导对话框。

参考系统原生授权弹窗的排版：应用图标 + 「允许…使用您的…」标题 + 一句说明
+ 「去授权 / 已完成」两个按钮。只在 macOS 使用；Windows 的权限错误仍走
QMessageBox，避免改变 Windows 既有交互。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from core.i18n import make_tr
from core.logger import log_exception, T
from core.ui_scale import configure_dialog_control, dialog_scaled
from ui.fluent_lite import FrostedFramelessDialog, PrimaryPushButton, PushButton
from ui.fluent_lite.titlebar import FluentTitleBar

_tr = make_tr("PermissionDialog")


class PermissionDialog(FrostedFramelessDialog):
    """权限引导弹窗：说明用途，并提供「去授权 / 已完成」两条路径。"""

    WINDOW_W = 460

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        message: str,
        detail: str = "",
        open_text: str = "",
        done_text: str = "",
        restart_text: str = "",
        on_open=None,
        on_restart=None,
    ):
        super().__init__(parent)
        self._on_open = on_open
        self._on_restart = on_restart

        title_bar = FluentTitleBar(self)
        configure_dialog_control(title_bar)
        self.setTitleBar(title_bar)
        title_bar.iconLabel.hide()
        title_bar.minBtn.hide()
        title_bar.maxBtn.hide()
        # 标题写在正文里（和系统授权弹窗一致），标题栏只留红黄绿，
        # 否则同一句「允许…使用您的…」会在标题栏和正文各出现一次。
        title_bar.titleLabel.hide()
        title_bar.setDoubleClickEnabled(False)

        self.setWindowTitle(title)
        self.setStyleSheet("background: transparent; border: none;")

        root = QVBoxLayout(self)
        title_height = self.titleBar.height() if getattr(self, "titleBar", None) else dialog_scaled(32)
        root.setContentsMargins(
            dialog_scaled(24),
            title_height + dialog_scaled(6),
            dialog_scaled(24),
            dialog_scaled(20),
        )
        root.setSpacing(dialog_scaled(18))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(dialog_scaled(16))

        icon_label = QLabel(self)
        icon_label.setFixedSize(dialog_scaled(56), dialog_scaled(56))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        try:
            from core.resource_manager import ResourceManager

            icon = QIcon(ResourceManager.get_resource_path("svg/托盘.svg"))
            if not icon.isNull():
                icon_label.setPixmap(icon.pixmap(dialog_scaled(48), dialog_scaled(48)))
        except Exception as e:
            log_exception(e, T("权限弹窗图标"))
        body.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(dialog_scaled(8))

        self.title_label = QLabel(title, self)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            f"font-size: {dialog_scaled(15)}px; font-weight: 700; background: transparent;"
        )
        text_column.addWidget(self.title_label)

        self.message_label = QLabel(message, self)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(
            f"font-size: {dialog_scaled(13)}px; background: transparent;"
        )
        text_column.addWidget(self.message_label)

        if detail:
            self.detail_label = QLabel(detail, self)
            self.detail_label.setWordWrap(True)
            self.detail_label.setStyleSheet(
                f"font-size: {dialog_scaled(12)}px; color: #8A8A8E; background: transparent;"
            )
            text_column.addWidget(self.detail_label)
        else:
            self.detail_label = None

        body.addLayout(text_column, 1)
        root.addLayout(body)
        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(dialog_scaled(10))
        buttons.addStretch(1)

        self.done_btn = PushButton(done_text or _tr("已完成"), self)
        configure_dialog_control(self.done_btn)
        self.done_btn.setFixedHeight(dialog_scaled(32))
        self.done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_btn.clicked.connect(self.accept)
        buttons.addWidget(self.done_btn)

        self.restart_btn = None
        if on_restart is not None:
            self.restart_btn = PushButton(restart_text or _tr("重启应用"), self)
            configure_dialog_control(self.restart_btn)
            self.restart_btn.setFixedHeight(dialog_scaled(32))
            self.restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.restart_btn.clicked.connect(self._restart)
            buttons.addWidget(self.restart_btn)

        self.open_btn = PrimaryPushButton(open_text or _tr("去授权"), self)
        configure_dialog_control(self.open_btn)
        self.open_btn.setFixedHeight(dialog_scaled(32))
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_settings)
        buttons.addWidget(self.open_btn)

        root.addLayout(buttons)

        # 宽度固定，高度按内容算：只设宽度会让对话框沿用默认高度（480+），
        # 底下一大片空白，看起来不像系统弹窗。
        self.setFixedWidth(dialog_scaled(self.WINDOW_W))
        root.activate()
        self.setFixedHeight(max(self.sizeHint().height(), dialog_scaled(190)))

    def _restart(self):
        if callable(self._on_restart):
            try:
                if self._on_restart():
                    return
            except Exception as e:
                log_exception(e, T("重启应用"))
        # 重启不了（例如开发环境直接跑 python）就退化成关闭弹窗，让用户手动重启
        self.accept()

    def _open_settings(self):
        if callable(self._on_open):
            try:
                self._on_open()
            except Exception as e:
                log_exception(e, T("打开系统权限设置"))
        # 不关窗：用户授权后还要回来点「已完成」复检一次
        self.done_btn.setFocus()


def show_screen_capture_dialog(parent=None, on_open=None, on_restart=None) -> bool:
    """截图前缺屏幕录制权限时的引导弹窗；返回用户是否点了「已完成」。"""
    dialog = PermissionDialog(
        parent,
        title=_tr("允许“积磊截图”使用您的屏幕录制"),
        message=_tr("积磊截图需要屏幕录制权限，才能截取屏幕内容并完成标注。"),
        detail=_tr("在系统设置里打开开关后，必须重启积磊截图才会生效。"),
        open_text=_tr("去授权"),
        done_text=_tr("已完成"),
        restart_text=_tr("重启应用"),
        on_open=on_open,
        on_restart=on_restart,
    )
    return dialog.exec() == PermissionDialog.DialogCode.Accepted


__all__ = ["PermissionDialog", "show_screen_capture_dialog"]
