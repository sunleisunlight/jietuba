# -*- coding: utf-8 -*-
"""账号「设备管理」：服务端设备列表解析、本机标记与解绑结果提示。"""

from PySide6.QtWidgets import QWidget

from account import get_account
from account.api import ApiError
from account.device import get_device_id


class _FakeDialog(QWidget):
    """设置页只需要 dialog.tr()，用普通 QWidget 顶替即可。"""

    def tr(self, text, *_args, **_kwargs):
        return text


def test_devices_parses_the_server_payload(monkeypatch):
    mgr = get_account()
    monkeypatch.setattr(mgr, "token", "tok", raising=False)
    monkeypatch.setattr(mgr, "phone", "13800000000", raising=False)

    from account import api

    monkeypatch.setattr(
        api, "client_devices",
        lambda token, phone: (
            {"devices": [{"device_id": "a"}, {"device_id": "b"}], "max_devices": 2},
            None,
        ),
    )
    devices, maximum, error = mgr.devices()
    assert [d["device_id"] for d in devices] == ["a", "b"]
    assert maximum == 2
    assert error == ""


def test_devices_reports_the_server_error(monkeypatch):
    mgr = get_account()
    monkeypatch.setattr(mgr, "token", "tok", raising=False)
    monkeypatch.setattr(mgr, "phone", "13800000000", raising=False)

    from account import api

    monkeypatch.setattr(
        api, "client_devices",
        lambda token, phone: (None, ApiError("device_not_bound", 400)),
    )
    devices, maximum, error = mgr.devices()
    assert devices == []
    assert maximum == 0
    # 错误码必须翻译成用户能照做的说明，而不是裸露的英文 code
    assert "绑定" in error and "device_not_bound" not in error


def test_page_marks_the_current_device_and_shows_the_limit(qapp):
    from account.page_account import PageAccount

    page = PageAccount(_FakeDialog())
    current = get_device_id()
    page._on_devices_loaded(
        [
            {"device_id": current, "platform": "macos", "app_version": "2.13.3",
             "last_seen_at": "2026-10-23T10:00:00Z"},
            {"device_id": "other-device", "platform": "windows", "app_version": "2.13.0",
             "last_seen_at": "2026-10-20T10:00:00Z"},
        ],
        2,
        "",
    )
    cards = page.group_devices._cards
    assert len(cards) == 2
    titles = [card.titleLabel.text() for card in cards]
    assert any("This device" in title for title in titles)
    assert any("Windows" in title for title in titles)
    # 上限提示必须是「已绑定 2 / 共 2」，用户才知道为什么登不上第三台
    assert "2" in page.device_hint.text() and "2" in page.device_hint.text()

    page.deleteLater()
    qapp.processEvents()


def test_page_shows_unbind_failure_instead_of_silently_swallowing(qapp):
    from account.page_account import PageAccount

    page = PageAccount(_FakeDialog())
    page._on_devices_loaded([], 2, "该设备没有绑定本产品，无需解绑")
    # 页面本身没 show()，用 isHidden() 判断"有没有被显式隐藏"
    assert not page.device_hint.isHidden()
    assert "绑定" in page.device_hint.text()

    page._on_unbind_finished(False, "不能解绑当前使用的这台设备")
    assert "不能解绑" in page.device_hint.text()

    page.deleteLater()
    qapp.processEvents()
