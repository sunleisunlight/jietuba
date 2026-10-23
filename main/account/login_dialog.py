# -*- coding: utf-8 -*-
"""积磊账号登录 / 注册对话框。

- 网络调用（login/register）一律在 QThread 中进行，绝不在 UI 线程阻塞；
- 同一组账号弹窗（登录门控 / 会员门控 / 会员套餐）共用本模块的暖色 QSS。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression, Qt, QThread, QTimer, Signal
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
_SMS_RE = re.compile(r"^\d{4,6}$")
# 与控制中心 validate_user_identity 的 DISPLAY_NAME_PATTERN 保持一致：
# 1-10 位中文 / 字母 / 数字，服务端会拒绝其它字符。
_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,10}$")

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

    finished_auth = Signal(object)  # AuthResult（含 sms 挑战）

    def __init__(self, mode: str, phone: str, pin: str, name: str = "",
                 sms_code: str = "", challenge_id: str = ""):
        super().__init__()
        self._mode = mode
        self._phone = phone
        self._pin = pin
        self._name = name
        self._sms_code = sms_code
        self._challenge_id = challenge_id

    def run(self) -> None:
        mgr = get_account()
        if self._mode == "register":
            result = mgr.register(self._phone, self._pin, self._name,
                                  sms_code=self._sms_code,
                                  challenge_id=self._challenge_id)
        else:
            result = mgr.login(self._phone, self._pin,
                               sms_code=self._sms_code,
                               challenge_id=self._challenge_id)
        self.finished_auth.emit(result)


class LoginDialog(QDialog):
    """积磊账号登录 / 注册对话框。"""

    MODE_LOGIN = "login"
    MODE_REGISTER = "register"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = self.MODE_LOGIN
        self._busy = False
        # 控制中心要求短信验证时，这里保存 challenge（含 challenge_id 与冷却时间）
        self._sms: dict | None = None
        # 发送还在冷却期、暂时拿不到 challenge：先把短信区露出来倒数，到点自动重发
        self._sms_waiting = False
        self._auto_resend = False
        self._resend_left = 0
        self._resend_timer = QTimer(self)
        self._resend_timer.setInterval(1000)
        self._resend_timer.timeout.connect(self._tick_resend)

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

        # 用户名只在注册模式显示（登录用不到，控制中心已存有昵称）
        self.name_label = BodyLabel(self.tr("Username"), self)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(self.name_label)

        self.name_edit = LineEdit(self)
        self.name_edit.setMaxLength(10)
        self.name_edit.setPlaceholderText(
            self.tr("1-10 Chinese characters, letters or digits")
        )
        self.name_edit.textChanged.connect(self._update_state)
        self.name_edit.returnPressed.connect(self._submit)
        root.addWidget(self.name_edit)

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

        # 确认安全码同样只在注册模式显示：注册必须两次输入一致
        self.confirm_label = BodyLabel(self.tr("Confirm security code"), self)
        self.confirm_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(self.confirm_label)

        self.confirm_edit = LineEdit(self)
        self.confirm_edit.setMaxLength(6)
        self.confirm_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.confirm_edit.setPlaceholderText(
            self.tr("Enter the same 6-digit security code again")
        )
        self.confirm_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self)
        )
        self.confirm_edit.textChanged.connect(self._update_state)
        self.confirm_edit.returnPressed.connect(self._submit)
        root.addWidget(self.confirm_edit)

        # 两次安全码不一致的就地提示（与服务端错误分开，互不覆盖）
        self.mismatch_label = QLabel("", self)
        self.mismatch_label.setObjectName("accountErrorLabel")
        self.mismatch_label.setWordWrap(True)
        self.mismatch_label.setStyleSheet("font-size: 12px;")
        self.mismatch_label.hide()
        root.addWidget(self.mismatch_label)

        # 短信验证码：控制中心在新号注册 / 新设备登录时会发一条短信，
        # 必须在这里给出输入框，否则用户收到验证码却没地方填。
        self.sms_label = BodyLabel(self.tr("SMS verification code"), self)
        self.sms_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(self.sms_label)

        sms_row = QHBoxLayout()
        sms_row.setContentsMargins(0, 0, 0, 0)
        sms_row.setSpacing(8)

        self.sms_edit = LineEdit(self)
        self.sms_edit.setMaxLength(6)
        self.sms_edit.setPlaceholderText(
            self.tr("Enter the code we just texted you")
        )
        self.sms_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self)
        )
        self.sms_edit.textChanged.connect(self._update_state)
        self.sms_edit.returnPressed.connect(self._submit)
        sms_row.addWidget(self.sms_edit, 1)

        self.resend_btn = TransparentPushButton(
            self.tr("Resend code"), self
        )
        self.resend_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resend_btn.clicked.connect(self._resend_sms)
        sms_row.addWidget(self.resend_btn, 0)
        root.addLayout(sms_row)

        self.sms_hint = CaptionLabel("", self)
        self.sms_hint.setObjectName("accountHintLabel")
        self.sms_hint.setWordWrap(True)
        root.addWidget(self.sms_hint)

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
        # 登录与注册是两个 purpose，旧 challenge 不能复用
        self._clear_sms()
        self.error_label.hide()
        self._update_state()

    def _update_state(self) -> None:
        register_mode = self._mode == self.MODE_REGISTER
        for widget in (self.name_label, self.name_edit,
                       self.confirm_label, self.confirm_edit):
            widget.setVisible(register_mode)

        sms_active = self._sms is not None or self._sms_waiting
        for widget in (self.sms_label, self.sms_edit,
                       self.resend_btn, self.sms_hint):
            widget.setVisible(sms_active)
        # 短信阶段由 sms_hint 单独说明，底部那句"安全码不是短信验证码"要收起来，
        # 否则两个提示叠在一起反而互相打架。
        self.hint_label.setVisible(not sms_active)
        # 验证码发出后，手机号 / 安全码 / 昵称不能再改：挑战是按这组信息签发的
        for edit in (self.phone_edit, self.name_edit,
                     self.pin_edit, self.confirm_edit):
            edit.setEnabled(not self._busy and not sms_active)
        self.sms_edit.setEnabled(not self._busy and self._sms is not None)
        self.switch_btn.setEnabled(not self._busy and not sms_active)

        if sms_active:
            if self._resend_left > 0:
                self.resend_btn.setText(
                    self.tr("Resend in {seconds}s").format(seconds=self._resend_left)
                )
                self.resend_btn.setEnabled(False)
            else:
                self.resend_btn.setText(self.tr("Resend code"))
                self.resend_btn.setEnabled(not self._busy)
            if self._sms is None:
                # 冷却期里还没有 challenge，验证码暂时无处可验
                self.submit_btn.setText(self.tr("Please wait…"))
                self.submit_btn.setEnabled(False)
                return
            # 短信区展开后按钮必须回到"登录/注册"，不能一直停在"请稍候…"
            self.submit_btn.setText(
                self.tr("Create Account") if register_mode else self.tr("Sign In")
            )
            valid = (
                _PHONE_RE.match(self.phone_edit.text()) is not None
                and _PIN_RE.match(self.pin_edit.text()) is not None
                and _SMS_RE.match(self.sms_edit.text()) is not None
            )
            self.submit_btn.setEnabled(valid and not self._busy)
            return

        if not register_mode:
            self.submit_btn.setText(self.tr("Sign In"))
            self.switch_btn.setText(self.tr("New here? Create an account"))
            self.hint_label.setText(
                self.tr(
                    "Any Jilei account can sign in here. The security code is the "
                    "6-digit number you set, not an SMS verification code."
                )
            )
            self.mismatch_label.hide()
            valid = (
                _PHONE_RE.match(self.phone_edit.text()) is not None
                and _PIN_RE.match(self.pin_edit.text()) is not None
            )
        else:
            self.submit_btn.setText(self.tr("Create Account"))
            self.switch_btn.setText(self.tr("Already registered? Sign in"))
            self.hint_label.setText(
                self.tr(
                    "Set a username and a 6-digit security code. Existing Jilei "
                    "account: enter your current security code to unlock this app."
                )
            )
            pin = self.pin_edit.text()
            confirm = self.confirm_edit.text()
            mismatch = bool(confirm) and confirm != pin
            self.mismatch_label.setText(
                self.tr("The two security codes do not match.") if mismatch else ""
            )
            self.mismatch_label.setVisible(mismatch)
            valid = (
                _PHONE_RE.match(self.phone_edit.text()) is not None
                and _NAME_RE.match(self.name_edit.text().strip()) is not None
                and _PIN_RE.match(pin) is not None
                and confirm == pin
            )
        self.submit_btn.setEnabled(valid and not self._busy)

    # ---------------------------------------------------- 短信验证码

    def _apply_sms(self, sms: dict) -> None:
        """服务端要求短信验证：显示输入框、提示已发送到哪个号码、开始重发倒计时。"""
        previous_id = (self._sms or {}).get("challenge_id")
        self._sms = sms
        self._sms_waiting = False
        self._auto_resend = False
        if sms.get("challenge_id") != previous_id:
            self.sms_edit.clear()

        warning = str(sms.get("warning") or "")
        masked = str(sms.get("masked_phone") or "")
        if warning:
            self.sms_hint.setText(warning)
        elif masked:
            self.sms_hint.setText(
                self.tr("Code sent to {phone}").format(phone=masked)
            )
        else:
            self.sms_hint.setText(self.tr("Code sent. Please check your messages."))

        try:
            self._resend_left = max(0, int(sms.get("retry_after") or 0))
        except (TypeError, ValueError):
            self._resend_left = 0
        if self._resend_left > 0:
            self._resend_timer.start()
        else:
            self._resend_timer.stop()

        self._update_state()
        self.sms_edit.setFocus()

    def _clear_sms(self) -> None:
        self._sms = None
        self._sms_waiting = False
        self._auto_resend = False
        self._resend_left = 0
        self._resend_timer.stop()
        self.sms_edit.clear()
        self.sms_hint.clear()

    def _tick_resend(self) -> None:
        if self._resend_left > 0:
            self._resend_left -= 1
        if self._resend_left <= 0:
            self._resend_left = 0
            self._resend_timer.stop()
            if self._auto_resend and not self._busy:
                # 冷却结束：自动再发一次，用户不用自己盯着秒数重按
                self._auto_resend = False
                self._resend_sms()
                return
        self._update_state()

    def _resend_sms(self) -> None:
        """不带验证码再提交一次，服务端会重发（冷却期内返回 sms_too_frequent）。"""
        if self._busy or self._resend_left > 0:
            return
        if self._sms is None and not self._sms_waiting:
            return
        self.error_label.hide()
        self._start_auth(sms_code="", challenge_id="")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            for edit in (self.phone_edit, self.name_edit, self.pin_edit,
                         self.confirm_edit, self.sms_edit):
                edit.setEnabled(False)
            self.resend_btn.setEnabled(False)
            self.switch_btn.setEnabled(False)
            self.submit_btn.setText(self.tr("Please wait…"))
            self.submit_btn.setEnabled(False)
        else:
            self._update_state()

    def _start_auth(self, sms_code: str, challenge_id: str) -> None:
        self._set_busy(True)
        thread = _AuthThread(
            self._mode, self.phone_edit.text(), self.pin_edit.text(),
            self.name_edit.text().strip() if self._mode == self.MODE_REGISTER else "",
            sms_code, challenge_id,
        )
        _RUNNING_THREADS.add(thread)
        thread.finished_auth.connect(self._on_auth_finished)
        thread.finished.connect(lambda: _retire_thread(thread))
        thread.start()

    def _submit(self) -> None:
        if self._busy:
            return
        if self._sms is None and self._sms_waiting:
            # 冷却期里还没有 challenge，重发交给倒计时，不在这里重复打服务端
            return
        phone = self.phone_edit.text()
        pin = self.pin_edit.text()

        if self._sms is not None:
            sms_code = self.sms_edit.text()
            if not _SMS_RE.match(sms_code):
                self.sms_edit.setFocus()
                return
            if not _PHONE_RE.match(phone) or not _PIN_RE.match(pin):
                return
            self.error_label.hide()
            self._start_auth(sms_code, str(self._sms.get("challenge_id") or ""))
            return

        if self._mode == self.MODE_REGISTER:
            name = self.name_edit.text().strip()
            if not _NAME_RE.match(name):
                return
            if not _PIN_RE.match(pin) or self.confirm_edit.text() != pin:
                return
        elif not _PIN_RE.match(pin):
            return
        if not _PHONE_RE.match(phone):
            return

        self.error_label.hide()
        self._start_auth("", "")

    def _on_auth_finished(self, result) -> None:
        self._busy = False
        if getattr(result, "ok", False):
            if self.isVisible():
                self.accept()
            return
        if not self.isVisible():
            return

        sms = getattr(result, "sms", None)
        if sms:
            self.error_label.hide()
            self._apply_sms(sms)
            self._set_busy(False)
            return

        message = (
            getattr(result, "message", "")
            or self.tr("Sign-in failed, please try again")
        )
        retry_after = int(getattr(result, "retry_after", 0) or 0)
        if retry_after > 0:
            # 服务端还在短信冷却期（sms_too_frequent）：先把短信区显示出来并倒数，
            # 到点自动重发，避免用户"收到过验证码却始终没有输入框"。
            self._sms = None
            self._sms_waiting = True
            self._auto_resend = True
            self._resend_left = retry_after
            self.sms_edit.clear()
            self.sms_hint.setText(message)
            self.sms_hint.show()
            self._resend_timer.start()
            self.error_label.hide()
            self._set_busy(False)
            return

        self.error_label.setText(message)
        self.error_label.show()
        if self._sms is not None:
            # 验证码错了：清空重填，短信区保持可见
            self.sms_edit.clear()
            self.sms_edit.setFocus()
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
