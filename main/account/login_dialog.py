# -*- coding: utf-8 -*-
"""积磊账号登录 / 注册对话框。

- 网络调用（login/register）一律在 QThread 中进行，绝不在 UI 线程阻塞；
- 同一组账号弹窗（登录门控 / 会员门控 / 会员套餐）共用本模块的暖色 QSS。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression, Qt, QThread, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from account import get_account
from core.ui_theme import get_ui_theme
from ui.fluent_lite import (
    BodyLabel, CaptionLabel, LineEdit, PrimaryPushButton, TransparentPushButton,
)

_PHONE_RE = re.compile(r"^\d{11}$")
_PIN_RE = re.compile(r"^\d{6}$")

# 提前关闭对话框时仍在跑的线程由模块集合保活，避免 QThread 被析构。
_RUNNING_THREADS: set[QThread] = set()


def account_dialog_qss() -> str:
    """账号系列对话框共用的暖色 / 深色背景样式。"""
    t = get_ui_theme().tokens
    bg = "#FFFBF8" if not t.is_dark else "#24201C"
    error_color = "#C42B1C" if not t.is_dark else "#FF9B9B"
    return f"""
        QDialog {{ background: {bg}; }}
        QLabel {{ color: {t.text}; background: transparent; }}
        QLabel#accountHintLabel, QLabel#accountFooterLabel,
        QLabel#accountSubLabel {{ color: {t.text_muted}; }}
        QLabel#accountErrorLabel {{ color: {error_color}; }}
        QLabel#accountBrandLabel {{ color: {t.text}; }}
        QLabel#accountPriceLabel {{ color: {t.text}; }}
        QLabel#accountPayHintLabel {{ color: {t.text_muted}; }}
    """


class _AuthThread(QThread):
    """后台执行 login/register，结果经信号回 UI 线程。"""

    finished_auth = Signal(bool, str)

    def __init__(self, mode: str, phone: str, pin: str):
        super().__init__()
        self._mode = mode
        self._phone = phone
        self._pin = pin

    def run(self) -> None:
        mgr = get_account()
        if self._mode == "register":
            ok, errmsg = mgr.register(self._phone, self._pin)
        else:
            ok, errmsg = mgr.login(self._phone, self._pin)
        self.finished_auth.emit(bool(ok), errmsg or "")


class LoginDialog(QDialog):
    """积磊账号登录 / 注册对话框。"""

    MODE_LOGIN = "login"
    MODE_REGISTER = "register"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = self.MODE_LOGIN
        self._busy = False

        self.setWindowTitle("积磊截图")
        self.setObjectName("accountLoginDialog")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(360)

        self._build_ui()
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)
        self._update_state()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)

        brand = QLabel("积磊截图", self)
        brand.setObjectName("accountBrandLabel")
        brand.setStyleSheet(
            "font-size: 23px; font-weight: 700; background: transparent;"
        )
        root.addWidget(brand)

        subtitle = CaptionLabel(
            self.tr("Sign in to use clipboard history and other account features"),
            self,
        )
        subtitle.setObjectName("accountSubLabel")
        subtitle.setWordWrap(False)
        root.addWidget(subtitle)
        root.addSpacing(6)

        phone_label = BodyLabel(self.tr("Phone number"), self)
        phone_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(phone_label)

        self.phone_edit = LineEdit(self)
        self.phone_edit.setMaxLength(11)
        self.phone_edit.setPlaceholderText(self.tr("Enter 11-digit phone number"))
        self.phone_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,11}"), self)
        )
        self.phone_edit.textChanged.connect(self._update_state)
        self.phone_edit.returnPressed.connect(self._submit)
        root.addWidget(self.phone_edit)

        pin_label = BodyLabel(self.tr("Security code"), self)
        pin_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(pin_label)

        self.pin_edit = LineEdit(self)
        self.pin_edit.setMaxLength(6)
        self.pin_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.pin_edit.setPlaceholderText(self.tr("Enter your 6-digit security code"))
        self.pin_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self)
        )
        self.pin_edit.textChanged.connect(self._update_state)
        self.pin_edit.returnPressed.connect(self._submit)
        root.addWidget(self.pin_edit)

        self.hint_label = CaptionLabel("", self)
        self.hint_label.setObjectName("accountHintLabel")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("accountErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("font-size: 12px;")
        self.error_label.hide()
        root.addWidget(self.error_label)

        self.submit_btn = PrimaryPushButton("", self)
        self.submit_btn.setObjectName("accountSubmitButton")
        self.submit_btn.setMinimumHeight(38)
        self.submit_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.submit_btn.clicked.connect(self._submit)
        root.addWidget(self.submit_btn)

        self.switch_btn = TransparentPushButton("", self)
        self.switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch_btn.clicked.connect(self._switch_mode)
        switch_row = QHBoxLayout()
        switch_row.addStretch(1)
        switch_row.addWidget(self.switch_btn)
        switch_row.addStretch(1)
        root.addLayout(switch_row)

        root.addStretch(1)

        footer = CaptionLabel(
            self.tr(
                "Screenshots and annotation are free forever without signing in."
            ),
            self,
        )
        footer.setObjectName("accountFooterLabel")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

    def _apply_theme(self, _tokens=None) -> None:
        self.setStyleSheet(account_dialog_qss())

    # -------------------------------------------------------------- 交互逻辑

    def _switch_mode(self) -> None:
        if self._busy:
            return
        if self._mode == self.MODE_LOGIN:
            self._mode = self.MODE_REGISTER
        else:
            self._mode = self.MODE_LOGIN
        self.error_label.hide()
        self._update_state()

    def _update_state(self) -> None:
        if self._mode == self.MODE_LOGIN:
            self.submit_btn.setText(self.tr("Sign In"))
            self.switch_btn.setText(self.tr("New here? Create an account"))
            self.hint_label.setText(
                self.tr(
                    "The security code is the 6-digit number you set, "
                    "not an SMS verification code."
                )
            )
        else:
            self.submit_btn.setText(self.tr("Create Account"))
            self.switch_btn.setText(self.tr("Already registered? Sign in"))
            self.hint_label.setText(
                self.tr(
                    "New phone number: set a 6-digit security code. "
                    "Existing Jilei account: enter your current security code."
                )
            )

        valid = (
            _PHONE_RE.match(self.phone_edit.text()) is not None
            and _PIN_RE.match(self.pin_edit.text()) is not None
        )
        self.submit_btn.setEnabled(valid and not self._busy)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for edit in (self.phone_edit, self.pin_edit):
            edit.setEnabled(not busy)
        self.switch_btn.setEnabled(not busy)
        if busy:
            self.submit_btn.setText(self.tr("Please wait…"))
            self.submit_btn.setEnabled(False)
        else:
            self._update_state()

    def _submit(self) -> None:
        if self._busy:
            return
        phone = self.phone_edit.text()
        pin = self.pin_edit.text()
        if not _PHONE_RE.match(phone) or not _PIN_RE.match(pin):
            return

        self.error_label.hide()
        self._set_busy(True)

        thread = _AuthThread(self._mode, phone, pin)
        _RUNNING_THREADS.add(thread)
        thread.finished_auth.connect(self._on_auth_finished)
        thread.finished.connect(lambda: _retire_thread(thread))
        thread.start()

    def _on_auth_finished(self, ok: bool, errmsg: str) -> None:
        self._busy = False
        if ok:
            if self.isVisible():
                self.accept()
            return
        if not self.isVisible():
            return
        self.error_label.setText(errmsg or self.tr("Sign-in failed, please try again"))
        self.error_label.show()
        self._set_busy(False)


def _retire_thread(thread: QThread) -> None:
    _RUNNING_THREADS.discard(thread)
    thread.deleteLater()


def prompt_login(parent: QWidget | None = None) -> bool:
    """模态弹出登录 / 注册对话框，返回最终是否已登录。"""
    if get_account().is_logged_in:
        return True
    dialog = LoginDialog(parent)
    return (
        dialog.exec() == QDialog.DialogCode.Accepted
        and get_account().is_logged_in
    )
