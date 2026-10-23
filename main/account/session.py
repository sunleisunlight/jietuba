# -*- coding: utf-8 -*-
"""积磊账号会话与功能门控（单例）。

设计取向——"感觉不到收费"：
- 门控判断只读本地缓存，瞬时返回，绝不阻塞截图/备注操作；
- 网络请求全部在后台线程完成，乐观放行、事后对齐；
- 网络故障永远放行（不能让断网导致软件不能用），只有服务端明确返回
  「额度不足」时才在下次动作弹门控；
- 界面不显示剩余次数、不做任何营销提醒，直到真正撞到墙。

额度规则：
- 游客（未登录）：每设备 20 次备注，第 21 次弹登录；
- 登录用户：注册即送 1000 次（无任何提示）；会员（月卡/两年/永久）不限次；
  超过 1000 次且非会员才弹开通会员。
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QSettings, Signal

from core.logger import log_warning, T

from . import api, constants as C
from . import token_store


@dataclass(frozen=True)
class AuthResult:
    """登录 / 注册结果。

    ``sms`` 非空表示控制中心要求短信验证码：本次已经发出短信（或命中发送
    冷却），调用方必须把验证码输入框显示出来，再用 ``sms_code`` +
    ``challenge_id`` 重新提交。
    """

    ok: bool
    message: str = ""
    sms: Optional[dict] = None
    # 短信发送冷却中（sms_too_frequent / sms_send_failed）时的剩余秒数；
    # 界面据此倒计时，到点自动重新发码，而不是让用户自己反复点。
    retry_after: int = 0


class AccountManager(QObject):
    """登录态、权益缓存与门控的唯一入口。"""

    # 登录态变化（登录/退出/会员状态刷新），UI 据此更新账号入口
    state_changed = Signal()
    # 备注额度用尽：游客→需登录；会员→需开通
    note_gate_required = Signal(str)   # "login" | "membership"

    def __init__(self):
        super().__init__()
        self._s = QSettings("JileiScreenshot", "JileiScreenshot")
        self.token: str = ""
        self.phone: str = ""
        self.name: str = ""
        self.is_frozen: bool = False
        # 服务端是否拒绝过当前令牌（只在内存里记一笔，不动已保存的登录凭证）。
        # 用于"服务端暂时不认这个令牌"的诊断与后续重试，不影响本机登录态。
        self._token_rejected: bool = False
        # 账号权益快照
        self.balance_units: int = -1          # -1 表示未知（离线）
        self.unlimited_active: bool = False
        self.unlimited_permanent: bool = False
        self.unlimited_expires_at: str = ""
        # 游客额度快照（服务端返回）
        self.guest_total: int = C.GUEST_NOTE_UNITS_FALLBACK
        self.guest_remaining: int = -1        # -1 未知
        self._hydrate()

    # ------------------------------------------------------------ 持久化快照

    def _hydrate(self):
        self.token = token_store.load_token()
        self.phone = token_store.get_phone()
        self.name = token_store.get_name()
        snap = self._s.value("account/entitlement", None)
        if isinstance(snap, str) and snap:
            try:
                self._apply_entitlement(json.loads(snap))
            except Exception:
                pass
        self.guest_remaining = int(self._s.value("account/guest_remaining", -1))
        self.guest_total = int(self._s.value("account/guest_total", C.GUEST_NOTE_UNITS_FALLBACK))

    def _persist_entitlement(self, data: dict):
        self._s.setValue("account/entitlement", json.dumps(data, ensure_ascii=False))
        self._s.sync()

    def _apply_entitlement(self, d: dict):
        self.is_frozen = bool(d.get("is_frozen", False))
        self.balance_units = int(d.get("export_balance_units", -1) or -1)
        self.unlimited_active = bool(d.get("unlimited_active", False))
        self.unlimited_permanent = bool(d.get("unlimited_permanent", False))
        self.unlimited_expires_at = d.get("unlimited_expires_at") or ""

    @property
    def is_logged_in(self) -> bool:
        return bool(self.token and self.phone)

    @property
    def is_member(self) -> bool:
        """会员（不限量会员生效中，含永久）。"""
        return self.unlimited_active or self.unlimited_permanent

    # ------------------------------------------------------------ 启动 / 刷新

    def startup(self):
        """应用启动时调用：后台恢复权益，不阻塞启动。"""
        threading.Thread(target=self.refresh, daemon=True).start()

    def refresh(self):
        """拉取最新权益（后台线程安全）。登录读 entitlement，匿名读游客额度。

        服务端说令牌失效（401）时**只标记、不删除本地登录**：已保存的令牌与手机号
        留在原处，登录态保持不变。原因是这个刷新每次启动都会跑一遍，删掉登录就得
        让用户重新登录一次（这正是"每次更新软件都要重新登录"的由来——升级后第一次
        启动的刷新若碰上令牌失效，凭证就被清掉了）。标记之后下次刷新会再验一次，
        服务端恢复/令牌仍有效时自动转回正常，用户那边全程不需要重新登录。
        """
        if self.is_logged_in:
            data, err = api.entitlement(self.token, self.phone)
            if data and data.get("ok", True):
                self._token_rejected = False
                self._apply_entitlement(data)
                self._persist_entitlement(data)
                self.state_changed.emit()
            elif err and err.status == 401:
                # 令牌失效：安静记一笔，保持登录态（门控继续读本地缓存、乐观放行）
                self._token_rejected = True
                log_warning(T("登录令牌被服务端拒绝（{status}），本机登录态保持不变，"
                              "下次刷新再验", status=err.status), "Account")
            else:
                self._refresh_guest()
        else:
            self._refresh_guest()

    def _refresh_guest(self):
        data, err = api.guest_capabilities()
        if data and data.get("ok", True) and not data.get("authenticated", False):
            self.guest_total = int(data.get("guest_units_total", C.GUEST_NOTE_UNITS_FALLBACK))
            self.guest_remaining = int(data.get("guest_units_remaining", -1))
            self._s.setValue("account/guest_total", self.guest_total)
            self._s.setValue("account/guest_remaining", self.guest_remaining)
            self._s.sync()
            self.state_changed.emit()

    # ------------------------------------------------------------ 登录 / 退出

    def login(self, phone: str, pin: str, sms_code: str = "",
              challenge_id: str = "") -> "AuthResult":
        data, err = api.login(phone, pin, sms_code=sms_code, challenge_id=challenge_id)
        if err is None:
            sms = _sms_challenge(data)
            if sms is not None:
                return AuthResult(False, sms.get("warning", ""), sms)
            ok, message = self._consume_auth(data, phone)
            return AuthResult(ok, message)
        if err.code == "product_registration_required":
            # 积磊账号是通用的：这个手机号在控制中心有账号，只是还没开通过本产品。
            # 用同一手机号 + 同一安全码幂等补开（服务端只会补开产品、不会重复发权益），
            # 用户不需要再走一遍注册。短信验证码要一起带过去，否则会被要求再发一次。
            return self.register(phone, pin, "", sms_code=sms_code,
                                 challenge_id=challenge_id)
        return AuthResult(False, _human_error(err),
                          retry_after=_sms_retry_after(err))

    def register(self, phone: str, pin: str, name: str = "", sms_code: str = "",
                 challenge_id: str = "") -> "AuthResult":
        data, err = api.register(phone, pin, name, sms_code=sms_code,
                                 challenge_id=challenge_id)
        if err is not None:
            return AuthResult(False, _human_error(err),
                              retry_after=_sms_retry_after(err))
        sms = _sms_challenge(data)
        if sms is not None:
            return AuthResult(False, sms.get("warning", ""), sms)
        ok, message = self._consume_auth(data, phone)
        return AuthResult(ok, message)

    def _consume_auth(self, data: dict, phone: str) -> tuple[bool, str]:
        token = str(data.get("device_access_token") or "")
        if not token:
            return False, "服务器未返回登录凭证，请稍后重试"
        name = str(data.get("user_name") or data.get("name") or "")
        self.token, self.phone, self.name = token, phone, name
        token_store.save_token(token, phone, name)
        self._apply_entitlement(data)
        self._persist_entitlement(data)
        self.state_changed.emit()
        # 登录后再后台拉一次完整权益（注册赠送可能在落库后才可见）
        threading.Thread(target=self.refresh, daemon=True).start()
        return True, ""

    def logout(self):
        self._do_logout_local()
        self.state_changed.emit()
        threading.Thread(target=self._refresh_guest, daemon=True).start()

    def _do_logout_local(self):
        token_store.clear_token()
        self.token = ""
        self.phone = ""
        self.name = ""
        self.balance_units = -1
        self.unlimited_active = False
        self.unlimited_permanent = False
        self.unlimited_expires_at = ""
        self.is_frozen = False
        self._s.remove("account/entitlement")
        self._s.sync()

    # ------------------------------------------------------------ 功能门控

    def can_use_clipboard(self) -> bool:
        """剪贴板历史必须登录。"""
        return self.is_logged_in

    def can_create_custom_group(self) -> bool:
        """剪贴板自定义分组需会员（登录是前提）。"""
        return self.is_logged_in and self.is_member

    def can_create_note(self) -> bool:
        """是否允许再创建一条备注（读本地缓存，瞬时返回）。

        未知/离线一律放行，只有明确"余额为 0 且非会员"才拦截。
        """
        if self.is_frozen:
            return False
        if self.is_logged_in:
            if self.is_member:
                return True
            # 余额未知（离线）放行；明确为 0 才拦
            return self.balance_units != 0
        # 游客
        if self.guest_remaining < 0:
            return True   # 未知放行
        return self.guest_remaining > 0

    def note_gate_reason(self) -> str:
        """can_create_note() 为 False 时，门控弹窗应展示哪种诉求。"""
        if not self.is_logged_in:
            return "login"
        return "membership"

    def consume_note(self):
        """成功创建一条备注后调用：乐观扣减本地计数，后台上报结算。

        不阻塞调用方、不抛异常。服务端返回额度不足时刷新本地缓存，下次门控生效。
        """
        if self.is_logged_in:
            if not self.is_member and self.balance_units > 0:
                self.balance_units -= 1
            token, phone = self.token, self.phone

            def _call(eid):
                d1, e1 = api.export_start(token, phone, eid)
                _settle_login(e1, d1, token, phone, eid)
            threading.Thread(target=_call, args=(uuid.uuid4().hex,), daemon=True).start()
        else:
            if self.guest_remaining > 0:
                self.guest_remaining -= 1
                self._s.setValue("account/guest_remaining", self.guest_remaining)
                self._s.sync()

            def _call(eid):
                d1, e1 = api.guest_export_start(eid)
                if e1 is None:
                    api.guest_export_finish(eid, "success")
                elif e1.code == "export_balance_insufficient":
                    self.guest_remaining = 0
                    self._s.setValue("account/guest_remaining", 0)
                    self.state_changed.emit()
                    self.note_gate_required.emit("login")
            threading.Thread(target=_call, args=(uuid.uuid4().hex,), daemon=True).start()


def _settle_login(err_start, data_start, token, phone, eid):
    if err_start is None:
        api.export_finish(token, phone, eid, "success")
        # 以服务端预占返回的最新余额为准回写
        if isinstance(data_start, dict):
            rem = data_start.get("export_balance_units")
            if rem is not None:
                mgr = get_account()
                mgr.balance_units = int(rem)
                mgr.state_changed.emit()
        return
    if err_start.code == "export_balance_insufficient":
        mgr = get_account()
        mgr.balance_units = 0
        mgr.state_changed.emit()
        mgr.note_gate_required.emit("membership")
    elif err_start.status == 401:
        # 同上：只标记令牌被拒，不删除已保存的登录，避免用户被反复要求重新登录
        get_account()._token_rejected = True
        log_warning(T("结算时令牌被服务端拒绝（401），本机登录态保持不变"), "Account")
    # 其它网络错误：保持乐观，不打扰


def _sms_retry_after(err) -> int:
    """只在短信发送类错误上返回冷却秒数；其它错误不触发界面的自动重发。"""
    if getattr(err, "code", "") not in ("sms_too_frequent", "sms_send_failed",
                                       "sms_daily_limit"):
        return 0
    if getattr(err, "code", "") == "sms_daily_limit":
        # 当日额度用完，重发也没用，别让界面空转到明天
        return 0
    return max(0, int(getattr(err, "retry_after", 0) or 0))


def _sms_challenge(data) -> Optional[dict]:
    """把控制中心 ``sms_required`` 应答整理成界面要用的字段；不是则返回 None。

    服务端在注册 / 新设备登录需要短信验证时会返回 200 + sms_required，
    里面带 challenge_id（二次提交要原样带回）、打码手机号、重发冷却与有效期。
    """
    if not isinstance(data, dict) or not data.get("sms_required"):
        return None

    def _int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return {
        "challenge_id": str(data.get("challenge_id") or data.get("challengeId") or ""),
        "masked_phone": str(data.get("masked_phone") or ""),
        "retry_after": _int(data.get("retry_after")),
        "expires_in": _int(data.get("expires_in")),
        "warning": str(data.get("send_warning") or ""),
    }


def _human_error(err) -> str:
    """把控制中心的错误码翻译成用户能照做的下一步。

    注册与登录是两条不同的补救路径，必须给出不同文案：以前只覆盖了少数几个
    错误码，其余（account_not_found / product_registration_required /
    account_already_exists / device_registration_already_used）全部落回
    兜底句「登录失败，请稍后重试」，用户看不出到底该登录还是该注册。
    """
    table = {
        "security_pin_incorrect": "手机号或 6 位安全码不正确",
        "security_pin_locked": "安全码错误次数过多，请 15 分钟后再试",
        "security_pin_invalid": "安全码必须是 6 位数字",
        "security_pin_setup_required": "该积磊账号还没有设置 6 位安全码，请先在积磊小程序里设置后再试",
        "device_limit_reached": "该账号绑定设备已达上限，请先在其它设备上解绑",
        "invalid_product_id": "客户端版本异常（产品未识别），请更新到最新版",
        "user_frozen": "账号已被停用，请联系客服",
        "network_unreachable": "当前网络无法连接积磊服务，请检查网络后重试",
        # 账号存在性 / 本产品开通状态（决定用户该点「登录」还是「注册账号」）
        "account_not_found": "该手机号还没有积磊账号，请点下方「注册账号」",
        "product_registration_required": "该积磊账号暂时无法开通积磊截图，请稍后重试",
        "account_already_exists": "该手机号已开通过积磊截图，请直接点「登录」",
        "device_registration_already_used": "本机已注册过其它积磊账号，请在本机登录原账号，或换一台电脑注册",
        # 设备 / 入参
        "device_id_required": "设备信息读取失败，请重启软件后重试",
        "login_fields_required": "请填写手机号与 6 位安全码",
        "invalid_phone": "手机号格式不正确，请输入 11 位手机号",
        "invalid_name": "账号昵称不合法，请稍后重试",
        # 短信验证码（与控制中心 sms_service.ERROR_MESSAGES 的错误码一一对应）
        "sms_too_frequent": "验证码发送太频繁，请稍后再试",
        "sms_daily_limit": "今日短信验证码次数已达上限，请明天再试或联系客服",
        "sms_code_required": "请先获取短信验证码",
        "sms_code_invalid": "验证码不正确，请重新输入",
        "sms_code_expired": "验证码已过期，请重新获取",
        "sms_challenge_invalid": "验证码请求已失效，请重新获取",
        "sms_attempts_exceeded": "验证码错误次数过多，请重新获取",
        "sms_send_failed": "短信发送失败，请稍后重试",
        "sms_not_configured": "短信服务尚未配置，请联系客服",
    }
    if err.code in table:
        return table[err.code]
    if err.code.startswith("http_"):
        return f"积磊服务暂时不可用（{err.code[5:]}），请稍后重试"
    return err.message or "登录失败，请稍后重试"


_manager: Optional[AccountManager] = None


def get_account() -> AccountManager:
    global _manager
    if _manager is None:
        _manager = AccountManager()
    return _manager
