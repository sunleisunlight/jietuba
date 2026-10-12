# -*- coding: utf-8 -*-
"""积磊会员套餐 / 下单对话框。

- 套餐列表与下单全部走 QThread，绝不阻塞 UI；
- 价格、套餐名一律以服务端返回为准，客户端不硬编码；
- 支付链接只允许 jilei.cc / sunget.top 域名，其它一律拦截。
"""
from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from account import api, get_account
from account.constants import CHECKOUT_HOST_SUFFIXES
from core.ui_theme import get_ui_theme
from ui.dialogs import show_info_dialog, show_warning_dialog
from ui.fluent_lite import (
    BodyLabel, CaptionLabel, PrimaryPushButton, PushButton,
)
from ui.fluent_lite.theme import ACCENT, ACCENT_SOFT, ui_tokens

from .login_dialog import account_dialog_qss, prompt_login

_RUNNING_THREADS: set[QThread] = set()

_PAGE_LOADING = 0
_PAGE_PLANS = 1
_PAGE_ERROR = 2


def _retire_thread(thread: QThread) -> None:
    _RUNNING_THREADS.discard(thread)
    thread.deleteLater()


def format_price(cents: Any) -> str:
    """cents(int) → 价格展示：490→¥4.9，9900→¥99。"""
    try:
        value = int(cents)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    if value % 100 == 0:
        return f"¥{value // 100}"
    text = f"{value / 100:.2f}".rstrip("0").rstrip(".")
    return f"¥{text}"


def is_safe_checkout_url(url: str) -> bool:
    """支付链接域名白名单：host 必须恰为或为 jilei.cc / sunget.top 的子域。"""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in CHECKOUT_HOST_SUFFIXES
    )


class _PlansThread(QThread):
    plans_loaded = Signal(object, object)

    def run(self) -> None:
        mgr = get_account()
        if mgr.is_logged_in:
            data, err = api.list_plans(mgr.token, mgr.phone)
        else:
            data, err = api.public_plans()
        self.plans_loaded.emit(data, err)


class _OrderThread(QThread):
    order_created = Signal(object, object)

    def __init__(self, token: str, phone: str, plan_id: str):
        super().__init__()
        self._token = token
        self._phone = phone
        self._plan_id = plan_id

    def run(self) -> None:
        data, err = api.create_order(self._token, self._phone, self._plan_id)
        self.order_created.emit(data, err)


class _EntitlementThread(QThread):
    entitlement_refreshed = Signal()

    def run(self) -> None:
        get_account().refresh()
        self.entitlement_refreshed.emit()


class MembershipDialog(QDialog):
    """会员套餐展示、下单与支付后刷新权益。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._busy = False
        self._plans: list[dict] = []
        self._subscribe_buttons: dict[str, PrimaryPushButton] = {}

        self.setWindowTitle(self.tr("Jilei Membership"))
        self.setObjectName("accountMembershipDialog")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(580, 480)
        self.setMinimumWidth(480)

        self._build_ui()
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)
        self._load_plans()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(10)

        title = QLabel(self.tr("Jilei Membership"), self)
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        root.addWidget(title)

        intro = CaptionLabel(
            self.tr(
                "Membership covers a small set of high-frequency premium features. "
                "Core screenshot features stay free forever."
            ),
            self,
        )
        intro.setObjectName("accountSubLabel")
        root.addWidget(intro)

        self.stack = QStackedWidget(self)

        self.loading_page = self._build_state_page()
        loading_lbl = BodyLabel(self.tr("Loading plans…"), self.loading_page)
        loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_page.layout().addWidget(loading_lbl)
        self.stack.addWidget(self.loading_page)

        self.plans_page = self._build_plans_page()
        self.stack.addWidget(self.plans_page)

        self.error_page = self._build_state_page()
        error_lbl = CaptionLabel(
            self.tr("Network error. Please try again later."), self.error_page
        )
        error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_page.layout().addWidget(error_lbl)
        retry_btn = PushButton(self.tr("Retry"), self.error_page)
        retry_btn.setMinimumWidth(110)
        retry_btn.clicked.connect(self._load_plans)
        self.error_page.layout().addWidget(retry_btn, 0, Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.error_page)

        root.addWidget(self.stack, 1)

        self.pay_hint = CaptionLabel(
            self.tr(
                "The payment page has opened in your browser. After completing "
                "payment, tap the button below to refresh your benefits."
            ),
            self,
        )
        self.pay_hint.setObjectName("accountPayHintLabel")
        self.pay_hint.setWordWrap(True)
        self.pay_hint.hide()
        root.addWidget(self.pay_hint)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.refresh_btn = PushButton(self.tr("I've paid, refresh benefits"), self)
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.clicked.connect(self._refresh_entitlement)
        self.refresh_btn.hide()
        bottom.addWidget(self.refresh_btn)
        bottom.addStretch(1)

        close_btn = PushButton(self.tr("Close"), self)
        close_btn.setMinimumHeight(36)
        close_btn.setMinimumWidth(88)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    def _build_state_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        return page

    def _build_plans_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        view = QWidget()
        view.setStyleSheet("background: transparent;")
        self.plans_layout = QVBoxLayout(view)
        self.plans_layout.setContentsMargins(0, 6, 6, 6)
        self.plans_layout.setSpacing(10)
        self.plans_layout.addStretch(1)
        scroll.setWidget(view)
        return scroll

    def _apply_theme(self, _tokens=None) -> None:
        self.setStyleSheet(account_dialog_qss())

    # ------------------------------------------------------------ 套餐加载

    def _load_plans(self) -> None:
        self.stack.setCurrentIndex(_PAGE_LOADING)
        thread = _PlansThread()
        _RUNNING_THREADS.add(thread)
        thread.plans_loaded.connect(self._on_plans_loaded)
        thread.finished.connect(lambda: _retire_thread(thread))
        thread.start()

    def _on_plans_loaded(self, data: object, err: object) -> None:
        if err is not None or not isinstance(data, dict):
            self.stack.setCurrentIndex(_PAGE_ERROR)
            return
        raw_plans = data.get("plans")
        if not isinstance(raw_plans, list) or not raw_plans:
            self.stack.setCurrentIndex(_PAGE_ERROR)
            return

        plans = [p for p in raw_plans if isinstance(p, dict)]
        plans.sort(key=lambda p: self._safe_int(p.get("sort_order"), 0))
        if not plans:
            self.stack.setCurrentIndex(_PAGE_ERROR)
            return

        self._plans = plans
        self._render_plans(plans)
        self.stack.setCurrentIndex(_PAGE_PLANS)

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _validity_text(self, plan: dict) -> str:
        """时长文案取服务端 valid_days：0 才是永久。

        注意不能看 is_unlimited——它表示「不限次数」，月卡/两年卡同样是 True，
        以前据此一律显示「永久使用」，把月卡写成了永久。
        """
        days = self._safe_int(plan.get("valid_days"), 0)
        if days <= 0:
            return self.tr("Permanent · free updates")
        return self.tr("%1 days").replace("%1", str(days))

    @staticmethod
    def _promo_prices(plan: dict) -> tuple[object, object]:
        """返回 (促销价, 标准价)；没有真实促销时促销价为 None。"""
        standard = plan.get("standard_price_cents")
        sale = plan.get("sale_price_cents")
        try:
            has_promo = (
                sale is not None and standard is not None
                and int(sale) > 0 and int(sale) < int(standard)
            )
        except (TypeError, ValueError):
            has_promo = False
        return (sale if has_promo else None), standard

    def _renewal_caption(self, plan: dict, standard_cents: object) -> str:
        """促销价下方的续费说明：「之后 ¥19.9/月」。"""
        price = format_price(standard_cents)
        if not price:
            return ""
        days = self._safe_int(plan.get("valid_days"), 0)
        if 28 <= days <= 31:
            return self.tr("Then %1/month").replace("%1", price)
        return self.tr("Then %1").replace("%1", price)

    def _render_plans(self, plans: list[dict]) -> None:
        # 清掉旧卡片（重试场景）
        while self.plans_layout.count() > 1:
            item = self.plans_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._subscribe_buttons.clear()

        t = ui_tokens(self)
        for plan in plans:
            plan_id = str(plan.get("id") or "")
            name = str(plan.get("name") or plan.get("short_name") or "")
            description = str(plan.get("description") or "")
            badge = str(plan.get("badge") or "")
            sale_cents, standard_cents = self._promo_prices(plan)
            price_cents = sale_cents if sale_cents is not None else standard_cents
            price = format_price(price_cents)
            renewal_caption = (
                self._renewal_caption(plan, standard_cents)
                if sale_cents is not None else ""
            )

            card = QFrame()
            card.setObjectName("accountPlanCard")
            card.setStyleSheet(
                f"""
                QFrame#accountPlanCard {{
                    background: {t.surface};
                    border: 1px solid {t.border};
                    border-radius: 12px;
                }}
                QFrame#accountPlanCard:hover {{ border-color: {ACCENT}; }}
                """
            )
            row = QHBoxLayout(card)
            row.setContentsMargins(18, 14, 18, 14)
            row.setSpacing(12)

            text_col = QVBoxLayout()
            text_col.setSpacing(3)

            name_row = QHBoxLayout()
            name_row.setSpacing(8)
            name_label = QLabel(name)
            name_label.setStyleSheet(
                "font-size: 15px; font-weight: 700; background: transparent;"
            )
            name_row.addWidget(name_label)
            if badge:
                badge_label = QLabel(badge)
                badge_label.setStyleSheet(
                    f"background: {ACCENT_SOFT}; color: {ACCENT}; "
                    "border-radius: 8px; padding: 1px 8px; font-size: 11px;"
                )
                name_row.addWidget(badge_label, 0, Qt.AlignmentFlag.AlignVCenter)
            name_row.addStretch(1)
            text_col.addLayout(name_row)

            if description:
                desc_label = CaptionLabel(description)
                desc_label.setWordWrap(True)
                text_col.addWidget(desc_label)

            validity_label = CaptionLabel(self._validity_text(plan))
            text_col.addWidget(validity_label)

            row.addLayout(text_col, 1)

            action_col = QVBoxLayout()
            action_col.setSpacing(6)
            price_label = QLabel(price)
            price_label.setObjectName("accountPriceLabel")
            price_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            price_label.setStyleSheet(
                f"font-size: 22px; font-weight: 700; color: {ACCENT};"
                " background: transparent;"
            )
            action_col.addWidget(price_label)

            if renewal_caption:
                renewal_label = CaptionLabel(renewal_caption)
                renewal_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                action_col.addWidget(renewal_label)

            subscribe_btn = PrimaryPushButton(self.tr("Subscribe"))
            subscribe_btn.setObjectName("subscribePlanButton")
            subscribe_btn.setMinimumWidth(104)
            subscribe_btn.setMinimumHeight(32)
            if not plan_id or not price:
                subscribe_btn.setEnabled(False)
            else:
                subscribe_btn.clicked.connect(
                    lambda _checked=False, pid=plan_id: self._subscribe(pid)
                )
            self._subscribe_buttons[plan_id] = subscribe_btn
            action_col.addWidget(
                subscribe_btn, 0, Qt.AlignmentFlag.AlignRight
            )
            row.addLayout(action_col, 0)

            self.plans_layout.insertWidget(self.plans_layout.count() - 1, card)

    # ------------------------------------------------------------ 下单 / 支付

    def _set_order_busy(self, busy: bool) -> None:
        self._busy = busy
        for plan_id, button in self._subscribe_buttons.items():
            button.setEnabled(not busy and bool(plan_id))

    def _subscribe(self, plan_id: str) -> None:
        if self._busy:
            return
        if not get_account().is_logged_in:
            if not prompt_login(self):
                return

        button = self._subscribe_buttons.get(plan_id)
        if button is None:
            return
        button.setText(self.tr("Placing order…"))
        self._set_order_busy(True)

        mgr = get_account()
        thread = _OrderThread(mgr.token, mgr.phone, plan_id)
        _RUNNING_THREADS.add(thread)
        thread.order_created.connect(
            lambda data, err, pid=plan_id: self._on_order_created(pid, data, err)
        )
        thread.finished.connect(lambda: _retire_thread(thread))
        thread.start()

    def _restore_subscribe_button(self, plan_id: str) -> None:
        button = self._subscribe_buttons.get(plan_id)
        if button is not None:
            button.setText(self.tr("Subscribe"))
        self._set_order_busy(False)

    def _on_order_created(self, plan_id: str, data: object, err: object) -> None:
        self._busy = False
        if err is not None:
            self._restore_subscribe_button(plan_id)
            message = (
                self.tr("Network error. Please try again later.")
                if getattr(err, "code", "") == "network_unreachable"
                else self.tr("Could not create the order. Please try again later.")
            )
            show_warning_dialog(self, self.tr("Jilei Membership"), message)
            return

        checkout_url = ""
        if isinstance(data, dict):
            checkout_url = str(
                data.get("checkout_url") or data.get("checkoutUrl") or ""
            )
        if not checkout_url or not is_safe_checkout_url(checkout_url):
            self._restore_subscribe_button(plan_id)
            show_warning_dialog(
                self,
                self.tr("Jilei Membership"),
                self.tr(
                    "The payment link is from an untrusted source and was blocked."
                ),
            )
            return

        self._set_order_busy(False)
        for button in self._subscribe_buttons.values():
            button.setText(self.tr("Subscribe"))
        webbrowser.open(checkout_url)
        self.pay_hint.show()
        self.refresh_btn.show()

    # ------------------------------------------------------------ 支付后刷新

    def _refresh_entitlement(self) -> None:
        if not get_account().is_logged_in:
            return
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText(self.tr("Refreshing…"))
        thread = _EntitlementThread()
        _RUNNING_THREADS.add(thread)
        thread.entitlement_refreshed.connect(self._on_entitlement_refreshed)
        thread.finished.connect(lambda: _retire_thread(thread))
        thread.start()

    def _on_entitlement_refreshed(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText(self.tr("I've paid, refresh benefits"))
        if get_account().is_member:
            show_info_dialog(
                self,
                self.tr("Activated"),
                self.tr(
                    "Your membership is active now. Thank you for your support!"
                ),
            )
            self.accept()
            return
        show_warning_dialog(
            self,
            self.tr("Jilei Membership"),
            self.tr(
                "Membership is not active yet. If you just finished paying, "
                "please wait a moment and tap refresh again."
            ),
        )
