# -*- coding: utf-8 -*-
"""账号会话：服务端说令牌失效时，**不能**动本机已保存的登录。

"每次更新软件都要重新登录"就是这么来的：升级后第一次启动会在后台跑一次权益
刷新（``AccountManager.startup`` → ``refresh``），这次刷新一旦撞上 401，旧代码
直接清掉已保存的令牌与手机号，用户下次就得重新登录一遍。现在只记一笔"服务端
不认这个令牌"，登录态原样留着，下次刷新再验；服务端恢复（或本来就只是抖动）
时自动转回正常，全程不需要用户重新登录。

注意区分：用户自己点「退出登录」当然要真删（见最后一条用例）。
"""
import pytest
from PySide6.QtCore import QSettings

from account import session, token_store
from account.api import ApiError


class _FakeTokenStore:
    """内存版令牌存储：测试不该碰到凭据管理器 / Keychain。"""

    def __init__(self, token="tok-1", phone="13800000000", name="小雷"):
        self.token = token
        self.phone = phone
        self.name = name
        self.cleared = 0

    def load_token(self):
        return self.token

    def save_token(self, token, phone="", name=""):
        self.token, self.phone, self.name = token, phone, name

    def clear_token(self):
        self.cleared += 1
        self.token = ""
        self.phone = ""
        self.name = ""

    def get_phone(self):
        return self.phone

    def get_name(self):
        return self.name


@pytest.fixture
def account(qapp, monkeypatch, tmp_path):
    """只连内存令牌存储、配置写到临时文件的 AccountManager。"""
    store = _FakeTokenStore()
    for name in ("load_token", "save_token", "clear_token", "get_phone", "get_name"):
        monkeypatch.setattr(token_store, name, getattr(store, name))
    ini = str(tmp_path / "account.ini")
    monkeypatch.setattr(
        session, "QSettings",
        lambda *args, **kwargs: QSettings(ini, QSettings.Format.IniFormat),
    )
    # 游客额度查询走的是真网络，这里掐掉，别让后台线程去连服务端
    monkeypatch.setattr(
        session.api, "guest_capabilities",
        lambda: (None, ApiError("network_unreachable", 0, "")),
    )
    manager = session.AccountManager()
    monkeypatch.setattr(session, "_manager", manager)
    return manager, store


def test_refresh_401_keeps_the_saved_login(account, monkeypatch):
    """刷新撞上 401：登录态与已保存的令牌都必须原样留着。"""
    manager, store = account
    monkeypatch.setattr(
        session.api, "entitlement",
        lambda token, phone: (None, ApiError("unauthorized", 401, "token rejected")),
    )

    assert manager.is_logged_in
    manager.refresh()

    assert manager.is_logged_in, "刷新撞上 401 之后登录态被清掉了——用户又得重新登录"
    assert (store.token, store.phone) == ("tok-1", "13800000000"), "已保存的凭证被删了"
    assert store.cleared == 0
    assert manager._token_rejected is True, "该记下服务端拒过这个令牌"


def test_refresh_recovers_once_the_token_is_accepted_again(account, monkeypatch):
    """标记只是"待复核"：下一次刷新成功就自动转回正常。"""
    manager, _store = account
    monkeypatch.setattr(
        session.api, "entitlement",
        lambda token, phone: (None, ApiError("unauthorized", 401, "")),
    )
    manager.refresh()
    assert manager._token_rejected is True

    monkeypatch.setattr(
        session.api, "entitlement",
        lambda token, phone: (
            {"ok": True, "export_balance_units": 952, "unlimited_active": True}, None,
        ),
    )
    manager.refresh()

    assert manager._token_rejected is False
    assert manager.is_logged_in and manager.is_member


def test_network_failure_never_touches_the_token(account, monkeypatch):
    """断网 / 5xx 同样不该动凭证：门控读本地缓存，乐观放行。"""
    manager, store = account
    monkeypatch.setattr(
        session.api, "entitlement",
        lambda token, phone: (None, ApiError("network_unreachable", 0, "offline")),
    )

    manager.refresh()

    assert manager.is_logged_in and store.cleared == 0
    assert manager._token_rejected is False, "网络错误不等于令牌被拒"


def test_settlement_401_does_not_clear_the_login(account):
    """结算（备注导出上报）撞上 401 时同理：只标记，不删登录。"""
    manager, store = account
    session._settle_login(
        ApiError("unauthorized", 401, ""), None, manager.token, manager.phone, "evt-1"
    )

    assert store.cleared == 0 and manager.is_logged_in


def test_logout_still_clears_everything(account):
    """用户自己点「退出登录」当然要真删——上面几条说的是"服务端拒绝"的情形。"""
    manager, store = account
    manager.logout()

    assert store.cleared == 1
    assert not manager.is_logged_in
