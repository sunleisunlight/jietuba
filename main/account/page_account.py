# -*- coding: utf-8 -*-
"""设置窗「积磊账号」页面。

- 未登录：账号说明 + 登录 / 注册入口；
- 已登录：脱敏手机号、昵称、会员状态、续费入口、退出登录；
- 不展示剩余次数 / 余额（产品要求无次数提醒）。

tr 文案统一走 ``dialog.tr``，翻译上下文为 SettingsDialog，与其它设置分页一致。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QWidget, QVBoxLayout

from account import get_account
from account.login_dialog import prompt_login
from account.membership_dialog import MembershipDialog
from core.ui_scale import dialog_scaled
from ui.dialogs import show_confirm_dialog
from ui.fluent_lite import (
    FluentIcon, PrimaryPushButton, PushButton, SettingCard, TransparentPushButton,
)
from ui.settings_ui.components import SettingCardGroup


def mask_phone(phone: str) -> str:
    """13800000000 → 138****0000；非 11 位时尽量脱敏。"""
    phone = (phone or "").strip()
    if len(phone) >= 7:
        return f"{phone[:3]}****{phone[-4:]}"
    if len(phone) >= 4:
        return f"**{phone[-2:]}"
    return phone or "—"


def format_expiry(iso: str) -> str:
    """ISO 到期时间 → 本地日期 YYYY-MM-DD；解析失败回退原串前 10 位。"""
    text = (iso or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return text[:10]


class PageAccount(QScrollArea):
    """积磊账号设置页。"""

    def __init__(self, dialog, parent: QWidget | None = None):
        super().__init__(parent)
        self._dialog = dialog
        self._built = False

        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        view = QWidget()
        view.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, dialog_scaled(20), dialog_scaled(10), dialog_scaled(20))
        layout.setSpacing(dialog_scaled(16))

        self.group_account = SettingCardGroup(self._tr("Jilei Account"), view)
        self.group_member = SettingCardGroup(self._tr("Membership"), view)

        # 未登录卡片
        self.logged_out_card = SettingCard(
            FluentIcon.PEOPLE,
            self._tr("Jilei Account"),
            self._tr(
                "Sign in to use clipboard history and other account features."
            ),
            parent=self.group_account,
        )
        login_btn = PrimaryPushButton(self._tr("Sign In / Register"), self.logged_out_card)
        login_btn.clicked.connect(self._open_login)
        self.logged_out_card.hBoxLayout.addWidget(
            login_btn, 0, Qt.AlignmentFlag.AlignRight
        )
        self.logged_out_card.hBoxLayout.addSpacing(dialog_scaled(16))
        self.group_account.addSettingCard(self.logged_out_card)

        # 已登录：账号信息卡
        self.account_card = SettingCard(
            FluentIcon.PEOPLE, "", "", parent=self.group_account
        )
        self.group_account.addSettingCard(self.account_card)

        # 会员状态卡
        self.member_card = SettingCard(
            FluentIcon.CERTIFICATE, "", "", parent=self.group_member
        )
        self.member_btn = PushButton("", self.member_card)
        self.member_btn.clicked.connect(self._open_membership)
        self.member_card.hBoxLayout.addWidget(
            self.member_btn, 0, Qt.AlignmentFlag.AlignRight
        )
        self.member_card.hBoxLayout.addSpacing(dialog_scaled(16))
        self.group_member.addSettingCard(self.member_card)

        self.logout_btn = TransparentPushButton(self._tr("Sign Out"), view)
        self.logout_btn.setIcon(FluentIcon.POWER_BUTTON)
        self.logout_btn.clicked.connect(self._logout)

        layout.addWidget(self.group_account)
        layout.addWidget(self.group_member)
        layout.addWidget(self.logout_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.setWidget(view)

        get_account().state_changed.connect(self.refresh_state)
        self._built = True
        self.refresh_state()

    def _tr(self, text: str) -> str:
        return self._dialog.tr(text)

    # ------------------------------------------------------------------ 动作

    def _open_login(self) -> None:
        prompt_login(self._dialog)

    def _open_membership(self) -> None:
        MembershipDialog(self._dialog).exec()
        self.refresh_state()

    def _logout(self) -> None:
        confirmed = show_confirm_dialog(
            self._dialog,
            self._tr("Sign Out"),
            self._tr("Sign out of this Jilei account on this device?"),
        )
        if confirmed:
            get_account().logout()

    # ------------------------------------------------------------------ 状态

    def refresh_state(self) -> None:
        if not self._built:
            return
        mgr = get_account()
        logged_in = mgr.is_logged_in

        self.logged_out_card.setVisible(not logged_in)
        self.account_card.setVisible(logged_in)
        self.group_member.setVisible(logged_in)
        self.logout_btn.setVisible(logged_in)

        if logged_in:
            display_name = mgr.name or self._tr("Jilei Account")
            self.account_card.setTitle(display_name)
            self.account_card.setContent(mask_phone(mgr.phone))

            if mgr.is_member:
                self.member_card.setTitle(self._tr("Membership active"))
                if mgr.unlimited_permanent:
                    self.member_card.setContent(
                        self._tr("Permanent member · free updates")
                    )
                else:
                    expiry = format_expiry(mgr.unlimited_expires_at)
                    self.member_card.setContent(
                        self._tr("Valid until %1").replace("%1", expiry)
                        if expiry
                        else self._tr("Membership active")
                    )
                self.member_btn.setText(self._tr("Renew / View Plans"))
            else:
                self.member_card.setTitle(self._tr("Free account"))
                self.member_card.setContent(
                    self._tr("Core screenshot features are free forever.")
                )
                self.member_btn.setText(self._tr("View Membership Plans"))

        # 卡片显隐变化后重算分组高度，避免留白或裁切
        self.group_account.refreshHeight()
        self.group_member.refreshHeight()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_state()


def create_account_page(dialog) -> PageAccount:
    """设置窗页面工厂。"""
    return PageAccount(dialog)
