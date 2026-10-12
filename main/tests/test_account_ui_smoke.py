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
        assert dialog.submit_btn.isEnabled() is True

        dialog.switch_btn.click()
        qapp.processEvents()
        assert dialog._mode == LoginDialog.MODE_LOGIN

        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()

    def test_failed_login_shows_inline_error(self, qapp, monkeypatch):
        mgr = get_account()
        monkeypatch.setattr(mgr, "login", lambda phone, pin: (False, "mock-login-error"))

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
