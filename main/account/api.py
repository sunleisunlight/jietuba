# -*- coding: utf-8 -*-
"""积磊控制中心 HTTP 客户端（仅标准库 urllib，不引入新依赖）。

约定：
- 所有方法返回 ``(data: dict | None, error: str)``，永不向调用方抛网络异常；
- 双 BASE 域名故障转移（品牌域 jilei.cc → cc.sunget.top）；
- 超时短，门控调用方据此做"放行优先"，网络问题不阻断截图。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from . import constants as C
from .device import get_device_id


class ApiError(Exception):
    def __init__(self, code: str, status: int = 0, message: str = "",
                 retry_after: int = 0):
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.message = message
        # 短信类错误的冷却秒数：界面据此倒计时并自动重发，用户不用反复手点
        try:
            self.retry_after = max(0, int(retry_after or 0))
        except (TypeError, ValueError):
            self.retry_after = 0


def _request(method: str, path: str, *, payload: Optional[dict] = None,
             token: str = "", phone: str = "", timeout: float = 8.0):
    """发起 JSON 请求，依次尝试两个 BASE 域名。

    返回 (data, None) 或 (None, ApiError)。4xx 业务错误不做域名转移（立刻返回，
    服务端给了明确应答说明链路是通的）；只对网络层错误/5xx 转移。
    """
    body = None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        C.H_DEVICE: get_device_id(),
    }
    if token:
        headers[C.H_TOKEN] = token
    if phone:
        headers[C.H_PHONE] = phone
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_err: Optional[ApiError] = None
    for base in C.BASE_URLS:
        url = base + path
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(raw) if raw else {}
                return data, None
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8", errors="ignore") or "{}")
            except Exception:
                err_body = {}
            err = ApiError(
                err_body.get("error_code") or err_body.get("error") or f"http_{e.code}",
                status=e.code,
                message=err_body.get("message") or "",
                retry_after=err_body.get("retry_after") or 0,
            )
            # 4xx 是明确业务应答，不换域名重试
            if 400 <= e.code < 500:
                return None, err
            last_err = err
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = ApiError("network_unreachable", message=str(e))
    return None, last_err or ApiError("network_unreachable")


# ---------------------------------------------------------------- 账号

def _auth_payload(security_pin: str, sms_code: str = "", challenge_id: str = "") -> dict:
    from main_app import APP_VERSION
    payload = {
        "phone": "",  # 由调用方填
        "name": "",
        "securityPIN": security_pin,
        "deviceId": get_device_id(),
        "platform": C.PLATFORM,
        "appVersion": APP_VERSION,
        "currentLibraryCount": 0,
        "productId": C.PRODUCT_ID,
    }
    # 控制中心在注册 / 新设备登录要求短信验证时，第二次提交必须原样带回
    # challengeId + 验证码；不填时保持原样，服务端会按"需要发码"处理。
    if sms_code:
        payload["smsCode"] = sms_code
    if challenge_id:
        payload["challengeId"] = challenge_id
    return payload


def _default_name(phone: str) -> str:
    """用户没填用户名时的兜底昵称（控制中心要求 1-10 位中文 / 字母 / 数字）。"""
    return f"积磊截图用户{phone[-4:]}" if len(phone) >= 4 else "积磊截图用户"


def register(phone: str, security_pin: str, name: str = "",
             sms_code: str = "", challenge_id: str = ""):
    p = _auth_payload(security_pin, sms_code, challenge_id)
    p["phone"] = phone
    # 用户名由用户在注册页填写；为空（自动开通本产品场景）时用兜底昵称，
    # 服务端对已存在的账号只会补开产品，不会覆盖它原有的用户名。
    p["name"] = (name or "").strip() or _default_name(phone)
    return _request("POST", "/api/v3/auth/register", payload=p)


def login(phone: str, security_pin: str, sms_code: str = "", challenge_id: str = ""):
    p = _auth_payload(security_pin, sms_code, challenge_id)
    p["phone"] = phone
    return _request("POST", "/api/v3/auth/login", payload=p)


# ---------------------------------------------------------------- 设备

def client_devices(token: str, phone: str):
    """已绑定本产品的设备列表（含当前设备）。

    服务端按产品隔离统计，积磊截图上限固定 2 台；返回体里带 max_devices。
    """
    return _request(
        "GET",
        f"/client/commerce/devices?product_id={C.PRODUCT_ID}",
        token=token, phone=phone, timeout=6.0,
    )


def unbind_device(token: str, phone: str, device_id: str):
    """解绑指定设备。服务端要求请求方自己已绑定，且不能解绑当前设备。"""
    return _request(
        "POST", "/client/commerce/devices/unbind",
        payload={"product_id": C.PRODUCT_ID, "device_id": device_id},
        token=token, phone=phone, timeout=8.0,
    )


# ---------------------------------------------------------------- 权益

def guest_capabilities():
    return _request(
        "GET",
        f"/client/products/{C.PRODUCT_ID}/capabilities?deviceId={get_device_id()}",
        timeout=6.0,
    )


def entitlement(token: str, phone: str):
    return _request(
        "GET",
        f"/client/products/{C.PRODUCT_ID}/entitlement?phone={urllib.parse.quote(phone)}"
        f"&deviceId={get_device_id()}",
        token=token, phone=phone, timeout=6.0,
    )


def export_start(token: str, phone: str, event_id: str, units: int = C.NOTE_UNITS):
    return _request(
        "POST", f"/client/products/{C.PRODUCT_ID}/exports/start",
        payload={"phone": phone, "deviceId": get_device_id(),
                 "exportEventId": event_id, "units": units, "format": "note"},
        token=token, phone=phone, timeout=8.0,
    )


def export_finish(token: str, phone: str, event_id: str, outcome: str):
    return _request(
        "POST", f"/client/products/{C.PRODUCT_ID}/exports/finish",
        payload={"phone": phone, "deviceId": get_device_id(),
                 "exportEventId": event_id, "outcome": outcome},
        token=token, phone=phone, timeout=8.0,
    )


def guest_export_start(event_id: str, units: int = C.NOTE_UNITS):
    return _request(
        "POST", f"/client/products/{C.PRODUCT_ID}/guest/exports/start",
        payload={"deviceId": get_device_id(), "exportEventId": event_id,
                 "units": units, "format": "note"},
        timeout=8.0,
    )


def guest_export_finish(event_id: str, outcome: str):
    return _request(
        "POST", f"/client/products/{C.PRODUCT_ID}/guest/exports/finish",
        payload={"deviceId": get_device_id(), "exportEventId": event_id,
                 "outcome": outcome},
        timeout=8.0,
    )


# ---------------------------------------------------------------- 商业

def list_plans(token: str, phone: str):
    return _request(
        "GET", f"/client/commerce/plans?product_id={C.PRODUCT_ID}",
        token=token, phone=phone, timeout=8.0,
    )


def public_plans():
    return _request(
        "GET", f"/public/products/{C.PRODUCT_ID}/plans", timeout=8.0)


def create_order(token: str, phone: str, plan_id: str):
    return _request(
        "POST", "/client/commerce/orders",
        payload={"product_id": C.PRODUCT_ID, "plan_id": plan_id,
                 "deviceId": get_device_id()},
        token=token, phone=phone, timeout=10.0,
    )


def list_orders(token: str, phone: str, limit: int = 20):
    return _request(
        "GET", f"/client/commerce/orders?product_id={C.PRODUCT_ID}&limit={limit}",
        token=token, phone=phone, timeout=8.0,
    )
