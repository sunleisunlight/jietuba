# -*- coding: utf-8 -*-
"""
积磊账号 UI 冒烟测试（QT_QPA_PLATFORM=offscreen）。

只验证四件事：
1. 登录 / 门控 / 会员对话框与账号设置页能实例化、show() 不崩；
2. 后台网络走 QThread：mock api 后套餐卡能渲染出来、失败有错误态；
3. 登录表单的手机号 / 安全码校验与后台登录回调不崩；
4. 纯展示辅助函数（价格 / 脱敏 / 到期日 / URL 白名单）行为正确。
"""
from PySide6.QtCore import QDeadlineTimer, QThread
from PySide6.QtWidgets import QPushButton

from account import AccountManager, get_account
from account.api import ApiError
from account.gate_dialog import GateLoginDialog, GateMembershipDialog
from account.login_dialog import LoginDialog
from account.membership_dialog import (
    MembershipDialog, format_price, is_safe_checkout_url,
)
from account.page_account import PageAccount, format_expiry, mask_phone
from core.i18n import make_tr


def _wait_until(qapp, predicate, timeout_ms=5000, interval_ms=10):
    deadline = QDeadlineTimer(timeout_ms)
    while not predicate() and not deadline.hasExpired():
        qapp.processEvents()
        QThread.msleep(interval_ms)
    qapp.processEvents()
    return bool(predicate())


_FAKE_PLANS = {
    "plans": [
        {
            "id": "monthly", "name": "月卡", "short_name": "monthly",
            "description": "一个月不限次", "standard_price_cents": 990,
            "sale_price_cents": 490, "valid_days": 30,
            "benefit_type": "unlimited", "is_unlimited": False,
            "badge": "热门", "sort_order": 10,
        },
        {
            "id": "two_year", "name": "两年卡",
            "standard_price_cents": 19900, "valid_days": 730,
            "is_unlimited": False, "sort_order": 20,
        },
        {
            "id": "permanent", "name": "永久卡",
            "description": "永久使用，保持更新",
            "standard_price_cents": 39900, "sale_price_cents": 19900,
            "valid_days": 0, "is_unlimited": True,
            "badge": "", "sort_order": 30,
        },
        # 非法项应被忽略，不能让整页崩掉
        "not-a-plan",
    ]
}


# ============================================================================
# LoginDialog
# ============================================================================

class TestLoginDialog:
    def test_validation_and_show(self, qapp, monkeypatch):
        dialog = LoginDialog()
        dialog.show()
        qapp.processEvents()

        # 初始：手机号 / 安全码为空，确定按钮禁用
        assert dialog.submit_btn.isEnabled() is False

        dialog.phone_edit.setText("123")
        dialog.pin_edit.setText("123456")
        qapp.processEvents()
        assert dialog.submit_btn.isEnabled() is False

        dialog.phone_edit.setText("13800000000")
        qapp.processEvents()
        assert dialog.submit_btn.isEnabled() is True

        # 切换到注册 / 再切回登录，不崩且不丢校验态
        dialog.switch_btn.click()
        qapp.processEvents()
        assert dialog._mode == LoginDialog.MODE_REGISTER
        # 注册必须填用户名 + 两次一致的安全码，缺一项都不能提交
        assert dialog.name_edit.isVisible()
        assert dialog.confirm_edit.isVisible()
        assert dialog.submit_btn.isEnabled() is False

        dialog.name_edit.setText("积磊用户")
        qapp.processEvents()
        assert dialog.submit_btn.isEnabled() is False

        dialog.confirm_edit.setText("123456")
        qapp.processEvents()
        assert dialog.submit_btn.isEnabled() is True

        # 两次安全码不一致：就地提示且不能提交
        dialog.confirm_edit.setText("654321")
        qapp.processEvents()
        assert dialog.submit_btn.isEnabled() is False
        assert dialog.mismatch_label.isVisible()

        dialog.confirm_edit.setText("123456")
        qapp.processEvents()

        dialog.switch_btn.click()
        qapp.processEvents()
        assert dialog._mode == LoginDialog.MODE_LOGIN
        assert not dialog.name_edit.isVisible()
        assert not dialog.confirm_edit.isVisible()
        assert dialog.submit_btn.isEnabled() is True

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_failed_login_shows_inline_error(self, qapp, monkeypatch):
        from account.session import AuthResult

        mgr = get_account()
        monkeypatch.setattr(
            mgr, "login",
            lambda phone, pin, **_: AuthResult(False, "mock-login-error"),
        )

        dialog = LoginDialog()
        dialog.show()
        dialog.phone_edit.setText("13800000000")
        dialog.pin_edit.setText("123456")
        dialog.submit_btn.click()

        ok = _wait_until(qapp, lambda: dialog.error_label.isVisible())
        assert ok
        assert dialog.error_label.text() == "mock-login-error"
        assert dialog.submit_btn.isEnabled() is True  # 失败后恢复可点

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_sms_required_reveals_code_input_and_verifies(self, qapp, monkeypatch):
        """控制中心要短信时，必须就地出现验证码输入框，并用它二次提交。

        回归：以前只把 sms_required 当成「服务器未返回登录凭证」，用户收到了
        短信验证码却没有任何地方能填。
        """
        from account.session import AuthResult

        mgr = get_account()
        calls = []

        def fake_login(phone, pin, sms_code="", challenge_id=""):
            calls.append((phone, pin, sms_code, challenge_id))
            if not sms_code:
                return AuthResult(False, "", {
                    "challenge_id": "chal-1",
                    "masked_phone": "138****0000",
                    "retry_after": 60,
                    "expires_in": 300,
                    "warning": "",
                })
            return AuthResult(True, "")

        monkeypatch.setattr(mgr, "login", fake_login)

        dialog = LoginDialog()
        dialog.show()
        dialog.phone_edit.setText("13800000000")
        dialog.pin_edit.setText("123456")
        dialog.submit_btn.click()

        assert _wait_until(qapp, lambda: dialog.sms_edit.isVisible())
        assert "138****0000" in dialog.sms_hint.text()
        # 按钮必须回到"登录"，不能一直停在"请稍候…"
        assert dialog.submit_btn.text() == "Sign In"
        # 手机号与安全码被锁定，避免更换后挑战失效
        assert dialog.phone_edit.isEnabled() is False
        # 未填验证码时不能提交
        assert dialog.submit_btn.isEnabled() is False

        dialog.sms_edit.setText("123456")
        qapp.processEvents()
        assert dialog.submit_btn.isEnabled() is True
        dialog.submit_btn.click()

        assert _wait_until(qapp, lambda: len(calls) >= 2)
        assert calls[-1][2] == "123456"
        assert calls[-1][3] == "chal-1"

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_sms_cooldown_reveals_input_and_auto_resends(self, qapp, monkeypatch):
        """冷却期（sms_too_frequent）也要先把短信区露出来，倒计时结束自动重发。

        回归：以前命中发送冷却时只弹一行错误，用户明明收到了验证码，
        界面上却始终没有输入框。
        """
        from account.session import AuthResult

        mgr = get_account()
        calls = []
        state = {"cooling": True}

        def fake_login(phone, pin, sms_code="", challenge_id=""):
            calls.append(sms_code)
            if state["cooling"]:
                state["cooling"] = False
                return AuthResult(
                    False, "验证码发送太频繁，请稍后再试", None, retry_after=1
                )
            return AuthResult(False, "", {
                "challenge_id": "chal-2", "masked_phone": "138****0000",
                "retry_after": 0, "expires_in": 300, "warning": "",
            })

        monkeypatch.setattr(mgr, "login", fake_login)

        dialog = LoginDialog()
        dialog.show()
        dialog.phone_edit.setText("13800000000")
        dialog.pin_edit.setText("123456")
        dialog.submit_btn.click()

        assert _wait_until(qapp, lambda: dialog.sms_edit.isVisible())
        assert "太频繁" in dialog.sms_hint.text()
        assert dialog.sms_edit.isEnabled() is False

        # 冷却结束后自动重发，拿到 challenge 后输入框随之可用
        assert _wait_until(qapp, lambda: dialog._sms is not None, timeout_ms=5000)
        assert dialog.sms_edit.isEnabled() is True
        assert len(calls) >= 2
        assert calls[1] == ""

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_switching_mode_clears_the_sms_challenge(self, qapp):
        dialog = LoginDialog()
        dialog.show()
        dialog._apply_sms({
            "challenge_id": "chal-1", "masked_phone": "138****0000",
            "retry_after": 60, "expires_in": 300, "warning": "",
        })
        assert dialog.sms_edit.isVisible()

        dialog._switch_mode()
        qapp.processEvents()
        assert dialog._sms is None
        assert dialog.sms_edit.isVisible() is False
        assert dialog.phone_edit.isEnabled() is True

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


# ============================================================================
# 后端错误码 → 用户可执行的下一步
# ============================================================================

class TestAuthErrorMessages:
    """每个账号错误码都要给出「我该点登录还是注册」的明确下一步。

    回归：以前只映射了少数错误码，account_not_found /
    product_registration_required / account_already_exists /
    device_registration_already_used 全部落回兜底句「登录失败，请稍后重试」，
    用户看不出原因也做不了补救。
    """

    def test_registration_failures_are_distinguishable(self):
        from account.session import _human_error

        expectations = {
            "account_not_found": "注册账号",
            # 登录会自动补开本产品，这个错误码只在补开也失败时出现
            "product_registration_required": "暂时无法开通",
            "account_already_exists": "登录",
            "device_registration_already_used": "本机",
            "security_pin_incorrect": "安全码",
            "security_pin_setup_required": "安全码",
            "device_limit_reached": "设备",
            "network_unreachable": "网络",
        }
        messages = set()
        for code, keyword in expectations.items():
            message = _human_error(ApiError(code, status=400))
            assert keyword in message, code
            assert "登录失败，请稍后重试" not in message, code
            messages.add(message)
        # 每条错误码的文案必须不同，否则又回到「看不出该做什么」
        assert len(messages) == len(expectations)

    def test_unknown_code_and_http_error_fall_back(self):
        from account.session import _human_error

        assert _human_error(ApiError("brand_new_code")) == "登录失败，请稍后重试"
        assert (
            _human_error(ApiError("http_404", status=404))
            == "积磊服务暂时不可用（404），请稍后重试"
        )

    def test_register_mode_hint_covers_existing_jilei_account(self, qapp):
        dialog = LoginDialog()
        dialog.switch_btn.click()
        assert dialog._mode == LoginDialog.MODE_REGISTER
        # 已有积磊账号的手机号必须知道「请输入原安全码」，否则会误以为要设新码
        hint = dialog.hint_label.text()
        assert "6-digit security code" in hint
        assert "Existing Jilei account" in hint
        dialog.deleteLater()
        qapp.processEvents()


# ============================================================================
# Gate 对话框
# ============================================================================

class TestGateDialogs:
    def test_gate_dialogs_show(self, qapp):
        login_gate = GateLoginDialog()
        login_gate.show()
        member_gate = GateMembershipDialog()
        member_gate.show()
        qapp.processEvents()

        assert login_gate.isVisible()
        assert member_gate.isVisible()

        login_gate.close()
        member_gate.close()
        login_gate.deleteLater()
        member_gate.deleteLater()
        qapp.processEvents()

    def test_require_login_passes_when_logged_in(self, qapp, monkeypatch):
        from account import gate_dialog

        monkeypatch.setattr(
            AccountManager, "is_logged_in", property(lambda self: True)
        )
        # 已登录不应弹任何对话框
        assert gate_dialog.require_login() is True


# ============================================================================
# MembershipDialog
# ============================================================================

class TestMembershipDialog:
    def test_plans_loaded_from_background_thread(self, qapp, monkeypatch):
        from account import api
        monkeypatch.setattr(api, "public_plans", lambda: (_FAKE_PLANS, None))
        monkeypatch.setattr(
            AccountManager, "is_logged_in", property(lambda self: False)
        )

        dialog = MembershipDialog()
        dialog.show()

        loaded = _wait_until(
            qapp, lambda: dialog.stack.currentIndex() == 1, timeout_ms=8000
        )
        assert loaded
        qapp.processEvents()

        buttons = dialog.findChildren(QPushButton, "subscribePlanButton")
        assert len(buttons) == 3
        # 三张卡都有有效 plan_id 与价格，按钮可用
        assert all(btn.isEnabled() for btn in buttons)

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_network_error_then_retry(self, qapp, monkeypatch):
        from account import api
        monkeypatch.setattr(
            api, "public_plans",
            lambda: (None, ApiError("network_unreachable", message="offline")),
        )
        monkeypatch.setattr(
            AccountManager, "is_logged_in", property(lambda self: False)
        )

        dialog = MembershipDialog()
        dialog.show()
        assert _wait_until(
            qapp, lambda: dialog.stack.currentIndex() == 2, timeout_ms=8000
        )

        # 恢复网络后点重试
        monkeypatch.setattr(api, "public_plans", lambda: (_FAKE_PLANS, None))
        retry_button = None
        for btn in dialog.error_page.findChildren(QPushButton):
            retry_button = btn
        assert retry_button is not None
        retry_button.click()
        assert _wait_until(
            qapp, lambda: dialog.stack.currentIndex() == 1, timeout_ms=8000
        )

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


# ============================================================================
# 积磊账号通用：登录即开通本产品
# ============================================================================

class TestLoginAutoOpensProduct:
    """积磊账号适用于所有软件：本产品没开通过时，登录应自动补开而不是报错。"""

    def _manager(self, monkeypatch):
        from account import session as account_session
        mgr = account_session.AccountManager()
        monkeypatch.setattr(
            mgr, "_consume_auth", lambda data, phone: (True, f"opened:{phone}")
        )
        return mgr

    def test_login_falls_back_to_open_product(self, monkeypatch, qapp):
        from account import api
        mgr = self._manager(monkeypatch)
        opened = []

        monkeypatch.setattr(
            api, "login",
            lambda phone, pin, **_: (None, ApiError("product_registration_required", 400)),
        )
        monkeypatch.setattr(
            api, "register",
            lambda phone, pin, name="", **_: (
                opened.append((phone, pin)) or {"device_access_token": "tok"}, None
            ),
        )

        result = mgr.login("13800000000", "123456")
        assert result.ok is True
        assert opened == [("13800000000", "123456")]
        assert result.message == "opened:13800000000"

    def test_login_still_reports_real_failure(self, monkeypatch, qapp):
        from account import api
        mgr = self._manager(monkeypatch)

        monkeypatch.setattr(
            api, "login",
            lambda phone, pin, **_: (None, ApiError("product_registration_required", 400)),
        )
        monkeypatch.setattr(
            api, "register",
            lambda phone, pin, name="", **_: (None, ApiError("account_already_exists", 409)),
        )

        result = mgr.login("13800000000", "123456")
        assert result.ok is False
        assert "已开通" in result.message


# ============================================================================
# 会员套餐卡片
# ============================================================================

class TestMembershipPlanCards:
    _PLANS = {
        "plans": [
            {
                "id": "jls-unlimited-monthly", "name": "积磊截图会员月卡",
                "valid_days": 30, "is_unlimited": True, "badge": "首月限时",
                "standard_price_cents": 1990, "sale_price_cents": 490, "sort_order": 110,
            },
            {
                "id": "jls-unlimited-2year", "name": "积磊截图会员两年卡",
                "valid_days": 730, "is_unlimited": True, "badge": "",
                "standard_price_cents": 9900, "sale_price_cents": None, "sort_order": 120,
            },
            {
                "id": "jls-unlimited-lifetime", "name": "积磊截图会员永久",
                "valid_days": 0, "is_unlimited": True, "badge": "",
                "standard_price_cents": 19900, "sale_price_cents": None, "sort_order": 130,
            },
        ]
    }

    def _texts(self, dialog):
        from PySide6.QtWidgets import QLabel
        return [w.text() for w in dialog.plans_page.findChildren(QLabel)]

    def test_validity_and_promo_pricing(self, monkeypatch, qapp):
        from account import api
        from account.membership_dialog import MembershipDialog

        monkeypatch.setattr(api, "public_plans", lambda: (self._PLANS, None))
        monkeypatch.setattr(
            AccountManager, "is_logged_in", property(lambda self: False)
        )

        dialog = MembershipDialog()
        dialog.show()
        assert _wait_until(
            qapp, lambda: dialog.stack.currentIndex() == 1, timeout_ms=8000
        )
        qapp.processEvents()
        texts = self._texts(dialog)

        # 首月限时：主价显示促销价，下面补一行续费价
        assert "¥4.9" in texts
        assert "Then ¥19.9/month" in texts
        # 时长按 valid_days：月卡 30 天、两年卡 730 天、永久才写永久
        assert "30 days" in texts
        assert "730 days" in texts
        assert "Permanent · free updates" in texts

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_no_promo_when_sale_equals_standard(self, monkeypatch, qapp):
        from account import api
        from account.membership_dialog import MembershipDialog

        plans = {
            "plans": [
                {
                    "id": "p1", "name": "月卡", "valid_days": 30, "is_unlimited": True,
                    "standard_price_cents": 490, "sale_price_cents": 490, "sort_order": 1,
                }
            ]
        }
        monkeypatch.setattr(api, "public_plans", lambda: (plans, None))
        monkeypatch.setattr(
            AccountManager, "is_logged_in", property(lambda self: False)
        )

        dialog = MembershipDialog()
        dialog.show()
        assert _wait_until(
            qapp, lambda: dialog.stack.currentIndex() == 1, timeout_ms=8000
        )
        qapp.processEvents()
        texts = self._texts(dialog)

        assert "¥4.9" in texts
        assert not [t for t in texts if t.startswith("Then ")]

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


# ============================================================================
# PageAccount
# ============================================================================

class _DialogStub:
    """只提供设置页工厂需要的 tr（上下文 SettingsDialog）。"""

    tr = staticmethod(make_tr("SettingsDialog"))


class TestPageAccount:
    @staticmethod
    def _force_state(mgr, **values):
        for key, value in values.items():
            setattr(mgr, key, value)

    def test_logged_out_then_logged_in(self, qapp):
        mgr = get_account()
        saved = {
            "token": mgr.token, "phone": mgr.phone, "name": mgr.name,
            "unlimited_active": mgr.unlimited_active,
            "unlimited_permanent": mgr.unlimited_permanent,
            "unlimited_expires_at": mgr.unlimited_expires_at,
        }
        try:
            self._force_state(
                mgr, token="", phone="", name="",
                unlimited_active=False, unlimited_permanent=False,
                unlimited_expires_at="",
            )
            page = PageAccount(_DialogStub())
            page.show()
            qapp.processEvents()

            assert page.logged_out_card.isVisible()
            assert not page.account_card.isVisible()
            assert not page.group_member.isVisible()
            assert not page.logout_btn.isVisible()

            # 模拟登录 + 永久会员
            self._force_state(
                mgr, token="tok", phone="13800000000", name="测试用户",
                unlimited_active=False, unlimited_permanent=True,
                unlimited_expires_at="",
            )
            mgr.state_changed.emit()
            qapp.processEvents()

            assert not page.logged_out_card.isVisible()
            assert page.account_card.isVisible()
            assert page.group_member.isVisible()
            assert page.logout_btn.isVisible()
            assert "138****0000" in page.account_card.contentLabel.text()
            assert page.member_btn.isVisible()

            page.close()
            page.deleteLater()
            qapp.processEvents()
        finally:
            self._force_state(mgr, **saved)


# ============================================================================
# 纯函数
# ============================================================================

class TestFormatters:
    def test_format_price(self):
        assert format_price(490) == "¥4.9"
        assert format_price(9900) == "¥99"
        assert format_price(19900) == "¥199"
        assert format_price(0) == "¥0"
        assert format_price(None) == ""
        assert format_price("abc") == ""

    def test_mask_phone(self):
        assert mask_phone("13800000000") == "138****0000"
        assert mask_phone("") == "—"

    def test_format_expiry(self):
        assert format_expiry("2027-05-06") == "2027-05-06"
        assert format_expiry("2027-05-06T01:02:03Z").startswith("2027-05-0")
        assert format_expiry("") == ""

    def test_checkout_url_whitelist(self):
        assert is_safe_checkout_url("https://cc.jilei.cc/pay/123")
        assert is_safe_checkout_url("https://cc.sunget.top/pay/123")
        assert is_safe_checkout_url("https://jilei.cc/x")
        # 近似域名 / 外域必须拦截
        assert not is_safe_checkout_url("https://eviljilei.cc/pay")
        assert not is_safe_checkout_url("https://example.com/pay")
        assert not is_safe_checkout_url("")
