# -*- coding: utf-8 -*-
"""设置窗「积磊账号」页面。

- 未登录：账号说明 + 登录 / 注册入口；
- 已登录：脱敏手机号、昵称、会员状态、续费入口、退出登录；
- 不展示剩余次数 / 余额（产品要求无次数提醒）。

tr 文案统一走 ``dialog.tr``，翻译上下文为 SettingsDialog，与其它设置分页一致。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QScrollArea, QWidget, QVBoxLayout

from account import get_account
from account.device import get_device_id
from account.login_dialog import prompt_login
from account.membership_dialog import MembershipDialog
from core.ui_scale import dialog_scaled
from ui.dialogs import show_confirm_dialog
from ui.fluent_lite import (
    CaptionLabel, FluentIcon, PrimaryPushButton, PushButton, SettingCard,
    TransparentPushButton,
)
from ui.settings_ui.components import SettingCardGroup


# 前台关闭页面后线程可能还在跑，模块级集合保活，避免 QThread 被析构
_RUNNING_THREADS: set[QThread] = set()


def _retire_thread(thread: QThread) -> None:
    _RUNNING_THREADS.discard(thread)
    thread.deleteLater()


class _DevicesThread(QThread):
    loaded = Signal(object, object, object)  # devices, max_devices, error

    def run(self) -> None:
        devices, maximum, error = get_account().devices()
        self.loaded.emit(devices, maximum, error)


class _UnbindThread(QThread):
    finished_unbind = Signal(bool, str)

    def __init__(self, device_id: str):
        super().__init__()
        self._device_id = device_id

    def run(self) -> None:
        ok, message = get_account().unbind_device(self._device_id)
        self.finished_unbind.emit(ok, message)


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


_PLATFORM_LABELS = {"macos": "macOS", "windows": "Windows", "linux": "Linux"}


def _format_seen(iso: str) -> str:
    """设备的 last_seen_at → 本地 YYYY-MM-DD HH:MM；解析不了就不显示。"""
    text = (iso or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


class PageAccount(QScrollArea):
    """积磊账号设置页。"""

    def __init__(self, dialog, parent: QWidget | None = None):
        super().__init__(parent)
        self._dialog = dialog
        self._built = False
        # 已拉过设备列表的 token：值变了才重新请求，避免每次 state_changed 都打网络
        self._devices_token = ""

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

        # 设备管理：服务端对积磊截图固定允许 2 台设备，这里列出已绑定的设备，
        # 让用户在换机/重装后能自己解绑，而不是被「已达上限」卡死。
        self.group_devices = SettingCardGroup(self._tr("Device Management"), view)
        self.device_hint = CaptionLabel("", view)
        self.device_hint.setWordWrap(True)
        self.device_hint.setVisible(False)

        layout.addWidget(self.group_account)
        layout.addWidget(self.group_member)
        layout.addWidget(self.group_devices)
        layout.addWidget(self.device_hint)
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

    # ------------------------------------------------------------------ 设备

    def _reload_devices(self) -> None:
        """后台拉取已绑定设备；网络请求绝不放在 UI 线程。"""
        if not get_account().is_logged_in:
            return
        self.device_hint.setText(self._tr("Loading devices…"))
        self.device_hint.setVisible(True)
        thread = _DevicesThread()
        _RUNNING_THREADS.add(thread)
        thread.loaded.connect(self._on_devices_loaded)
        thread.finished.connect(lambda t=thread: _retire_thread(t))
        thread.start()

    def _on_devices_loaded(self, devices, maximum, error) -> None:
        self.group_devices.clearSettingCards()
        if error:
            self.group_devices.setVisible(False)
            self.device_hint.setText(str(error))
            self.device_hint.setVisible(True)
            return

        items = [item for item in (devices or []) if isinstance(item, dict)]
        current_id = get_device_id()
        for item in items:
            self._add_device_card(item, current_id)

        limit = maximum or len(items)
        self.device_hint.setText(
            self._tr("Bound %1 of %2 devices")
            .replace("%1", str(len(items)))
            .replace("%2", str(limit))
        )
        self.group_devices.setVisible(bool(items))
        self.device_hint.setVisible(True)
        self.group_devices.refreshHeight()

    def _add_device_card(self, item: dict, current_id: str) -> None:
        device_id = str(item.get("device_id") or "")
        raw_platform = str(item.get("platform") or "").strip()
        platform = (
            _PLATFORM_LABELS.get(raw_platform.lower(), raw_platform)
            or self._tr("Unknown device")
        )
        is_current = bool(device_id) and device_id == current_id
        title = f"{platform} · {self._tr('This device')}" if is_current else platform

        parts = []
        version = str(item.get("app_version") or "").strip()
        if version:
            parts.append(f"v{version}")
        seen = _format_seen(str(item.get("last_seen_at") or ""))
        if seen:
            parts.append(self._tr("Last seen %1").replace("%1", seen))

        card = SettingCard(
            FluentIcon.APPLICATION, title, " · ".join(parts), parent=self.group_devices
        )
        if is_current:
            card.hBoxLayout.addWidget(
                CaptionLabel(self._tr("This device"), card),
                0,
                Qt.AlignmentFlag.AlignRight,
            )
        else:
            unbind_btn = PushButton(self._tr("Unbind"), card)
            unbind_btn.clicked.connect(
                lambda _=False, d=device_id, p=platform: self._unbind_device(d, p)
            )
            card.hBoxLayout.addWidget(
                unbind_btn, 0, Qt.AlignmentFlag.AlignRight
            )
        card.hBoxLayout.addSpacing(dialog_scaled(16))
        self.group_devices.addSettingCard(card)

    def _unbind_device(self, device_id: str, platform: str) -> None:
        if not device_id:
            return
        confirmed = show_confirm_dialog(
            self._dialog,
            self._tr("Unbind this device?"),
            self._tr(
                "%1 will need to sign in again to use clipboard history."
            ).replace("%1", platform),
        )
        if not confirmed:
            return
        thread = _UnbindThread(device_id)
        _RUNNING_THREADS.add(thread)
        thread.finished_unbind.connect(self._on_unbind_finished)
        thread.finished.connect(lambda t=thread: _retire_thread(t))
        thread.start()

    def _on_unbind_finished(self, ok: bool, message: str) -> None:
        if not ok:
            self.device_hint.setText(
                message or self._tr("Could not unbind this device.")
            )
            self.device_hint.setVisible(True)
            return
        self._reload_devices()

    # ------------------------------------------------------------------ 状态

    def refresh_state(self) -> None:
        if not self._built:
            return
        mgr = get_account()
        logged_in = mgr.is_logged_in

        self.logged_out_card.setVisible(not logged_in)
        self.account_card.setVisible(logged_in)
        self.group_member.setVisible(logged_in)
        self.group_devices.setVisible(logged_in)
        self.logout_btn.setVisible(logged_in)

        if not logged_in:
            self._devices_token = ""
            self.group_devices.clearSettingCards()
            self.device_hint.setVisible(False)
        elif self._devices_token != mgr.token:
            # 登录态变化时才拉一次；权益刷新也会发 state_changed，不能每次都打网络
            self._devices_token = mgr.token
            self._reload_devices()

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
        self.group_devices.refreshHeight()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_state()


def create_account_page(dialog) -> PageAccount:
    """设置窗页面工厂。"""
    return PageAccount(dialog)
