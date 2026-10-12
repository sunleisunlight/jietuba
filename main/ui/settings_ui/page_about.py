# -*- coding: utf-8 -*-
"""关于页面"""

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from core.ui_scale import dialog_scaled
from ui.fluent_lite import (
    SettingCard, FluentIcon,
    PushButton,
)
from .components import SettingCardGroup
from ui.update_flow import check_for_update_interactive, get_update_controller
from main_app import APP_VERSION


class _CheckButtonState(QObject):
    """让按钮忙碌态跟随更新控制器。

    以按钮为父对象，按钮随设置窗销毁时本对象一起销毁，控制器信号自动断开，
    不会回调到已删除的控件上。
    """

    def __init__(self, button: PushButton, dialog):
        super().__init__(button)
        self._button = button
        self._dialog = dialog
        controller = get_update_controller()
        controller.checking_changed.connect(self.apply)
        self.apply(controller.is_checking)

    @Slot(bool)
    def apply(self, busy: bool) -> None:
        self._button.setEnabled(not busy)
        self._button.setText(
            self._dialog.tr("Checking...") if busy
            else self._dialog.tr("Check for Updates")
        )


def create_about_page(dialog) -> QScrollArea:
    """创建情報页面 - Fluent 风格"""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    view = QWidget()
    view.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(view)
    layout.setContentsMargins(0, dialog_scaled(20), dialog_scaled(10), dialog_scaled(20))
    layout.setSpacing(dialog_scaled(16))

    # ── 关于信息 ─────────────────────────────────────────────
    group = SettingCardGroup(dialog.tr("About"), view)

    # 软件信息卡片
    name_card = SettingCard(
        FluentIcon.APPLICATION,
        dialog.tr("Version"),
        APP_VERSION,
        parent=group,
    )
    check_update_btn = PushButton(dialog.tr("Check for Updates"), name_card)
    check_update_btn.setObjectName("checkUpdateButton")
    name_card.hBoxLayout.addWidget(
        check_update_btn, 0, Qt.AlignmentFlag.AlignRight
    )
    name_card.hBoxLayout.addSpacing(dialog_scaled(16))
    group.addSettingCard(name_card)

    # 应用内更新：查控制中心清单，下载校验后一键重启安装。检查在后台线程里跑，
    # 按钮的忙碌/恢复由控制器信号驱动，点击后不会立刻弹回原状。
    check_update_btn.clicked.connect(check_for_update_interactive)
    _CheckButtonState(check_update_btn, dialog)

    layout.addWidget(group)
    layout.addStretch(1)
    scroll.setWidget(view)
    return scroll

 
