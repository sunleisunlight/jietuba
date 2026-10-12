# -*- coding: utf-8 -*-
"""关于页面"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from PySide6.QtCore import Qt
from core.ui_scale import dialog_scaled
from ui.fluent_lite import (
    SettingCard, FluentIcon,
    PushButton,
)
from .components import SettingCardGroup
from ui.update_flow import check_and_offer_update
from main_app import APP_VERSION


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

    def start_check():
        # 应用内更新：走积磊控制中心清单，支持下载校验后一键重启安装
        check_update_btn.setEnabled(False)
        check_update_btn.setText(dialog.tr("Checking..."))
        check_and_offer_update(dialog)
        check_update_btn.setEnabled(True)
        check_update_btn.setText(dialog.tr("Check for Updates"))

    check_update_btn.clicked.connect(start_check)

    layout.addWidget(group)
    layout.addStretch(1)
    scroll.setWidget(view)
    return scroll

 
