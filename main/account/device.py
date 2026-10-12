# -*- coding: utf-8 -*-
"""稳定设备 ID：一台机器一个 UUID，重装/升级/换账号都保持不变。

与积磊其它桌面客户端一致，设备 ID 用于游客额度去重、会员设备绑定与上限。
存于本产品自己的 QSettings（不再复用旧 jietuba 组织名）。
"""
import uuid

from PySide6.QtCore import QSettings

_KEY = "account/device_id"
_cache: str | None = None


def get_device_id() -> str:
    global _cache
    if _cache:
        return _cache
    s = QSettings("JileiScreenshot", "JileiScreenshot")
    value = str(s.value(_KEY, "") or "").strip()
    if not value:
        value = uuid.uuid4().hex
        s.setValue(_KEY, value)
        s.sync()
    _cache = value
    return value
