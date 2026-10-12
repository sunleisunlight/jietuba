# -*- coding: utf-8 -*-
"""功能门控对话框（安静、无营销味）：

- :func:`require_login` —— 未登录时提示登录；
- :func:`require_membership` —— 非会员时引导查看会员套餐。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from account import get_account
from ui.fluent_lite import (
    BodyLabel, CaptionLabel, PrimaryPushButton, PushButton,
)

from .login_dialog import account_dialog_qss, prompt_login
from .membership_dialog import MembershipDialog


class _GateDialog(QDialog):
    """门控对话框共用骨架：标题 + 说明 + 右侧主次按钮。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("accountGateDialog")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(380)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(26, 22, 26, 18)
        self._root.setSpacing(8)

        from core.ui_theme import get_ui_theme
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, _tokens=None) -> None:
        self.setStyleSheet(account_dialog_qss())

    def _add_heading(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._root.addWidget(label)
        return label

    def _add_body(self, text: str) -> CaptionLabel:
        label = CaptionLabel(text, self)
        label.setWordWrap(True)
        self._root.addWidget(label)
        return label

    def _add_buttons(self, primary_text: str, secondary_text: str) -> None:
        self._root.addSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)

        secondary_btn = PushButton(secondary_text, self)
        secondary_btn.setMinimumHeight(34)
        secondary_btn.setMinimumWidth(96)
        secondary_btn.clicked.connect(self.reject)
        row.addWidget(secondary_btn)

        primary_btn = PrimaryPushButton(primary_text, self)
        primary_btn.setMinimumHeight(34)
        primary_btn.setMinimumWidth(112)
        primary_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        primary_btn.clicked.connect(self.accept)
        row.addWidget(primary_btn)

        self._root.addLayout(row)


class GateLoginDialog(_GateDialog):
    """「此功能需要登录」门控。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Sign In Required"))
        self._add_heading(self.tr("This feature requires a Jilei account."))
        self._add_body(
            self.tr(
                "After signing in, clipboard history is free to use; "
                "core screenshot features stay free forever."
            )
        )
        self._add_buttons(self.tr("Sign In"), self.tr("Not now"))
        self._apply_theme()


class GateMembershipDialog(_GateDialog):
    """「此功能需要开通会员」门控。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Membership Required"))
        self._add_heading(self.tr("This feature requires an active membership."))

        benefits_title = BodyLabel(self.tr("Membership benefits:"), self)
        benefits_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        self._root.addWidget(benefits_title)
        for benefit in (
            self.tr("Custom clipboard groups"),
            self.tr("Unlimited notes"),
        ):
            item = CaptionLabel(f"•  {benefit}", self)
            item.setWordWrap(False)
            self._root.addWidget(item)

        self._add_buttons(
            self.tr("View Membership Plans"), self.tr("Maybe later")
        )
        self._apply_theme()


def require_login(parent: QWidget | None = None) -> bool:
    """需要登录的功能门控。已登录直接放行；点「登录」并登录成功返回 True。"""
    if get_account().is_logged_in:
        return True
    if GateLoginDialog(parent).exec() != QDialog.DialogCode.Accepted:
        return False
    return prompt_login(parent)


def require_membership(parent: QWidget | None = None) -> bool:
    """需要会员的功能门控。已是会员直接放行；走完开通流程返回 True。"""
    if get_account().is_member:
        return True
    if GateMembershipDialog(parent).exec() != QDialog.DialogCode.Accepted:
        return False
    if not get_account().is_logged_in and not prompt_login(parent):
        return False
    dialog = MembershipDialog(parent)
    return (
        dialog.exec() == QDialog.DialogCode.Accepted
        and get_account().is_member
    )
