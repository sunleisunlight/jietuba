# -*- coding: utf-8 -*-
"""控制中心通知轮询 —— 「控制中心一上传，在线客户端几分钟内就弹更新提示」。

dizhi-tool 就是这么做的：控制中心「发布中心」发布新版本时会自动生成一条
``kind == "update"`` 的通知（sunget-control-center notices.py::publish_release_notice），
客户端带游标增量轮询 ``/client/notices``（5 分钟一拍），见到 update 通知才去查真正的
更新清单——能不能装仍以清单（版本号 / 签名 / SHA-256）为准，绝不凭一条通知伪造状态。

之前只有"启动查一次 + 每 2 小时复查"，上传后最坏要等两小时，用户自然看不到弹窗。
"""
from __future__ import annotations

import json

import pytest

import ui.update_flow as update_flow
from core import notices as control_notices


@pytest.fixture
def restore_notice_cursor():
    original = update_flow.notice_cursor()
    yield
    update_flow.set_notice_cursor(original)


def _reset_controller(monkeypatch):
    monkeypatch.setattr(update_flow, "_controller", None)
    return update_flow.get_update_controller()


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _patch_urlopen(monkeypatch, payload, seen):
    def _open(req, timeout=None):
        seen.append(req.full_url)
        return _FakeResponse(payload)

    monkeypatch.setattr(control_notices.urllib.request, "urlopen", _open)


class TestFetchNotices:
    def test_请求带上产品与游标(self, monkeypatch):
        seen = []
        _patch_urlopen(monkeypatch, {"items": [{"id": "n1", "kind": "update"}]}, seen)

        items = control_notices.fetch_notices(after="cursor-9")

        assert items == [{"id": "n1", "kind": "update"}]
        assert seen, "没有发出任何请求"
        assert "productId=jilei-screenshot" in seen[0]
        assert "after=cursor-9" in seen[0]

    def test_网络异常一律返回空列表(self, monkeypatch):
        def _boom(*_args, **_kwargs):
            raise OSError("network down")

        monkeypatch.setattr(control_notices.urllib.request, "urlopen", _boom)

        assert control_notices.fetch_notices(after="") == []

    def test_返回结构异常也不抛异常(self, monkeypatch):
        seen = []
        _patch_urlopen(monkeypatch, {"items": "not-a-list"}, seen)

        assert control_notices.fetch_notices() == []

    def test_只认update类通知(self):
        update_items = [{"id": "a", "kind": "update"}, {"id": "b", "kind": "notice"}]
        plain_items = [{"id": "a", "kind": "notice"}, {"id": "b", "kind": ""}]

        assert control_notices.has_update_notice(update_items) is True
        assert control_notices.has_update_notice(plain_items) is False
        assert control_notices.newest_id(update_items, "old") == "b"
        assert control_notices.newest_id([], "old") == "old"


class TestControllerReactsToNotices:
    def test_update通知会触发一次真正的复查(
        self, monkeypatch, qapp, qtbot, restore_notice_cursor
    ):
        calls = []
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: calls.append(1))
        monkeypatch.setattr(update_flow, "show_info_dialog", lambda *a: None)
        controller = _reset_controller(monkeypatch)

        controller._on_notices([{"id": "cursor-1", "kind": "update"}])
        qtbot.waitUntil(lambda: not controller.is_checking, timeout=5000)

        assert calls == [1], "收到 update 通知必须去核一遍更新清单"
        assert update_flow.notice_cursor() == "cursor-1"

    def test_普通公告不触发复查(self, monkeypatch, qapp, qtbot, restore_notice_cursor):
        calls = []
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: calls.append(1))
        controller = _reset_controller(monkeypatch)

        controller._on_notices([{"id": "cursor-2", "kind": "notice"}])
        qapp.processEvents()

        assert calls == []
        assert update_flow.notice_cursor() == "cursor-2", "游标仍要推进，免得重复拉同一批"

    def test_轮询线程的结果回到GUI线程(
        self, monkeypatch, qapp, qtbot, restore_notice_cursor
    ):
        monkeypatch.setattr(
            control_notices, "fetch_notices",
            lambda after="": [{"id": "cursor-3", "kind": "notice"}],
        )
        controller = _reset_controller(monkeypatch)

        controller.start_notice_polling(interval_ms=60 * 60 * 1000)
        qtbot.waitUntil(lambda: update_flow.notice_cursor() == "cursor-3", timeout=5000)

        controller._notice_timer.stop()

    def test_启动自动检查同时开通知轮询(self, monkeypatch, qapp, qtbot):
        controller = _reset_controller(monkeypatch)
        monkeypatch.setattr(update_flow.updater, "check_for_update", lambda: None)
        monkeypatch.setattr(control_notices, "fetch_notices", lambda after="": [])

        update_flow.start_auto_update_checker()

        assert controller._periodic_timer is not None
        assert controller._notice_timer is not None
        assert controller._notice_timer.interval() == update_flow.NOTICE_POLL_INTERVAL_MS
        qtbot.waitUntil(lambda: not controller.is_checking, timeout=5000)
        controller._periodic_timer.stop()
        controller._notice_timer.stop()
