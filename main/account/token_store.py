# -*- coding: utf-8 -*-
"""设备访问令牌的安全存储。

- Windows：写入系统 Credential Manager（凭据管理器），随用户配置文件加密。
- macOS：写入 Keychain（通过 /usr/bin/security）。
- 平台 API 不可用时（异常环境）降级到 QSettings，保证登录流程不被阻断。

只存设备令牌与登录手机号，绝不存安全 PIN。
"""
import sys
import subprocess

from PySide6.QtCore import QSettings

from .constants import PRODUCT_ID

_GENERIC = "JileiScreenshot"
_TOKEN_TARGET = f"{_GENERIC}:device_token:{PRODUCT_ID}"
_PHONE_KEY = "account/phone"
_NAME_KEY = "account/name"


def _win_write(target: str, secret: str) -> bool:
    try:
        import win32cred
        cred = {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "CredentialBlob": secret,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }
        win32cred.CredWrite(cred, 0)
        return True
    except Exception:
        return False


def _win_read(target: str) -> str:
    try:
        import win32cred
        cred = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        blob = cred.get("CredentialBlob")
        if isinstance(blob, bytes):
            return blob.decode("utf-16-le", errors="ignore")
        return str(blob or "")
    except Exception:
        return ""


def _win_delete(target: str) -> None:
    try:
        import win32cred
        win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:
        pass


def _mac_write(account: str, secret: str) -> bool:
    try:
        subprocess.run(
            ["/usr/bin/security", "add-generic-password", "-a", account,
             "-s", _GENERIC, "-w", secret, "-U"],
            check=True, capture_output=True, timeout=10,
        )
        return True
    except Exception:
        return False


def _mac_read(account: str) -> str:
    try:
        r = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", account,
             "-s", _GENERIC, "-w"],
            check=True, capture_output=True, timeout=10, text=True,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _mac_delete(account: str) -> None:
    try:
        subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-a", account,
             "-s", _GENERIC],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:
        pass


def save_token(token: str, phone: str = "", name: str = "") -> None:
    s = QSettings("JileiScreenshot", "JileiScreenshot")
    if phone:
        s.setValue(_PHONE_KEY, phone)
    if name:
        s.setValue(_NAME_KEY, name)
    s.sync()
    account = phone or "device"
    ok = _win_write(_TOKEN_TARGET, token) if sys.platform == "win32" else _mac_write(account, token)
    if not ok:
        # 降级：系统安全存储不可用时落 QSettings（可运行优先）
        s.setValue("account/device_token_fallback", token)
        s.sync()


def load_token() -> str:
    account = get_phone() or "device"
    token = _win_read(_TOKEN_TARGET) if sys.platform == "win32" else _mac_read(account)
    if token:
        return token
    return str(QSettings("JileiScreenshot", "JileiScreenshot").value(
        "account/device_token_fallback", "") or "")


def clear_token() -> None:
    account = get_phone() or "device"
    if sys.platform == "win32":
        _win_delete(_TOKEN_TARGET)
    else:
        _mac_delete(account)
    s = QSettings("JileiScreenshot", "JileiScreenshot")
    s.remove("account/device_token_fallback")
    s.sync()


def get_phone() -> str:
    return str(QSettings("JileiScreenshot", "JileiScreenshot").value(_PHONE_KEY, "") or "")


def get_name() -> str:
    return str(QSettings("JileiScreenshot", "JileiScreenshot").value(_NAME_KEY, "") or "")
