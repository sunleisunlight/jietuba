# -*- coding: utf-8 -*-
"""系统权限设置页（macOS only）— 屏幕录制 / 辅助功能 / 输入监控 状态与引导。

只在 macOS 上挂载；Windows 不创建此页，保持原 UI 不变。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer

from core.ui_scale import dialog_scaled
from core import log_exception, T
from .components import SettingCardGroup, WhiteCard, apply_theme_text_style

_STATUS_ZH = {"granted": "已授权", "denied": "未授权", "not_requested": "未请求", "unknown": "未知"}
_STATUS_EN = {"granted": "Granted", "denied": "Denied", "not_requested": "Not Requested", "unknown": "Unknown"}


def _status_text(dialog, status: str) -> str:
    if dialog.tr("已授权") != "已授权":
        return _STATUS_EN.get(status, status)
    return _STATUS_ZH.get(status, status)


def _build_permission_row(dialog, parent, title: str, kind: str) -> QWidget:
    card = WhiteCard(parent)
    card.setFixedHeight(dialog_scaled(52))

    row = QHBoxLayout(card)
    row.setContentsMargins(dialog_scaled(16), 0, dialog_scaled(14), 0)
    row.setSpacing(dialog_scaled(10))
    row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    title_label = QLabel(title, card)
    apply_theme_text_style(title_label, 14)
    row.addWidget(title_label, 1)

    status_label = QLabel("…", card)
    status_label.setObjectName("PermissionStatus")
    status_label.setStyleSheet(
        "font-size: 13px; color: #909399; background: transparent;"
    )
    row.addWidget(status_label, 0, Qt.AlignmentFlag.AlignRight)

    open_btn = QPushButton(dialog.tr("Open Settings"), card)
    open_btn.setFixedSize(dialog_scaled(96), dialog_scaled(28))
    open_btn.setStyleSheet(
        "QPushButton { font-size: 12px; border-radius: 6px;"
        " background: rgba(0, 122, 255, 0.12); color: #007AFF; }"
        "QPushButton:hover { background: rgba(0, 122, 255, 0.22); }"
    )
    open_btn.clicked.connect(
        lambda _=False, k=kind: dialog._open_system_permission(k)
    )
    row.addWidget(open_btn)

    return card


def create_permissions_page(dialog) -> QWidget:
    """创建系统权限设置页（macOS）"""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    view = QWidget()
    view.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(view)
    layout.setContentsMargins(0, 0, 10, 0)
    layout.setSpacing(16)

    grp = SettingCardGroup(dialog.tr("System Permissions"), view)

    if hasattr(dialog, "_mac_permission_rows"):
        dialog._mac_permission_rows = {}
    dialog._mac_permission_rows = {
        "screen_capture": _build_permission_row(
            dialog, grp, dialog.tr("Screen Recording"), "screen_capture"),
        "accessibility": _build_permission_row(
            dialog, grp, dialog.tr("Accessibility"), "accessibility"),
        "input_monitoring": _build_permission_row(
            dialog, grp, dialog.tr("Input Monitoring"), "input_monitoring"),
    }
    for card in dialog._mac_permission_rows.values():
        grp.addSettingCard(card)

    layout.addWidget(grp)

    hint = QLabel(
        dialog.tr(
            "Permission requests are made per-feature when you first use them. "
            "Screen Recording is needed for capture; Accessibility enables smart "
            "control selection; Input Monitoring enables global input listeners."
        ),
        view,
    )
    hint.setWordWrap(True)
    hint.setStyleSheet("font-size: 12px; color: #909399; background: transparent;")
    layout.addWidget(hint)

    # 刷新按钮
    refresh_btn = QPushButton(dialog.tr("Refresh Status"), view)
    refresh_btn.setFixedWidth(dialog_scaled(140))
    refresh_btn.clicked.connect(
        lambda _=False: dialog._refresh_mac_permissions()
    )
    layout.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignLeft)

    layout.addStretch()
    scroll.setWidget(view)

    # 页面首次显示时刷新一次（延迟到事件循环就绪）
    QTimer.singleShot(100, lambda: getattr(dialog, "_refresh_mac_permissions", lambda: None)())
    return scroll
