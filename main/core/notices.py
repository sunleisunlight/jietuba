# -*- coding: utf-8 -*-
"""控制中心客户端通知的拉取（更新提醒 + 管理员公告）。

与 dizhi-tool 走的是同一条通道、同一套合同：

    GET /client/notices?productId=<产品>&after=<游标>&limit=<条数>
    → {"items": [{id, kind, title, body, priority, version, publishedAt}], "latestId": ""}

为什么靠它做「控制中心一上传就提醒」：
- 控制中心「发布中心」发布某个产品的新版本时，会自动生成一条 `kind == "update"`
  的通知（sunget-control-center `storage/repositories/notices.py::publish_release_notice`），
  客户端只要按游标增量轮询，就能在上传后的几分钟内主动弹出更新提示；
- 接口**允许匿名读取**（更新提醒必须在用户登录前就能送达），所以这里不带任何凭证；
- 通知本身只是"门铃"：能不能装仍然以更新清单（版本号 / 签名 / SHA-256）为准，
  绝不因为一条通知就伪造更新状态。

拉取失败、超时、返回畸形 JSON 一律返回空列表：通知只是锦上添花，绝不影响主流程。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from core import updater
from core.logger import log_warning, T

# 通知类型：update 由发布四件套自动生成，notice 由管理员手写
KIND_UPDATE = "update"

PRODUCT_ID = updater.PRODUCT_ID
BASE_URLS = updater.BASE_URLS
DEFAULT_LIMIT = 20


def fetch_notices(after: str = "", limit: int = DEFAULT_LIMIT, timeout: float = 8.0) -> list[dict]:
    """拉取游标之后的新通知；任何失败都返回空列表（不抛异常）。"""
    query = f"?productId={PRODUCT_ID}&after={after or ''}&limit={int(limit)}"
    for base in BASE_URLS:
        req = urllib.request.Request(
            base + "/client/notices" + query,
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                # 参数/游标不被接受：别再换域名重试，等下一轮用新游标即可
                log_warning(T("控制中心通知被拒绝: HTTP {code}", code=e.code), "Notices")
                return []
            continue
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
        items = data.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]
    return []


def has_update_notice(items) -> bool:
    """这批通知里有没有「有新版本」的提醒。"""
    return any(
        str(item.get("kind") or "").strip().lower() == KIND_UPDATE
        for item in items or ()
        if isinstance(item, dict)
    )


def newest_id(items, fallback: str = "") -> str:
    """这批通知里最新一条的 id（item 按发布顺序返回，最后一条最新）。"""
    newest = fallback
    for item in items or ():
        if not isinstance(item, dict):
            continue
        notice_id = str(item.get("id") or "").strip()
        if notice_id:
            newest = notice_id
    return newest
