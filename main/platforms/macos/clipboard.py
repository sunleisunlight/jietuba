# -*- coding: utf-8 -*-
"""macOS 剪贴板后端 — Qt/NSPasteboard 写入 + Command+V 粘贴注入。

写入策略：
  - 图片：QApplication.clipboard().setImage()（Qt 内部走 NSPasteboard）；
  - 文件引用：QMimeData + QUrl（public.file-url 类型）。
粘贴策略：
  - 先用 NSRunningApplication 激活目标应用，等焦点切过去后注入
    Command+V（CGEventPost，Quartz）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QMimeData, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication, QImage

from ..base.clipboard import ClipboardBackend
from .permissions import _ax_is_trusted

_CMD_V_DOWN = 9  # kVK_ANSI_V
_CMD_C_DOWN = 8  # kVK_ANSI_C
_CMD_KEY = 0x37  # kVK_Command

# 激活重试参数（与 Windows 版语义一致，约 200ms 上限）
_ACTIVATE_RETRY_MS = 20
_ACTIVATE_MAX_ATTEMPTS = 10


def _post_key_event(keycode: int, down: bool, *, command: bool = False) -> None:
    """注入一次键盘事件（CGEventCreateKeyboardEvent + CGEventPost）。"""
    import Quartz

    event = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
    if event is None:
        raise RuntimeError("无法创建 macOS 键盘事件")
    Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand if command else 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    # PyObjC 管理 Create 返回对象的生命周期，不手动 CFRelease。


def send_cmd_v() -> bool:
    """模拟按下 Command+V。"""
    return _send_command_shortcut(_CMD_V_DOWN)


def send_copy_shortcut() -> bool:
    """模拟按下 Command+C（智能翻译"备用复制快捷键"的 macOS 等价物）。"""
    return _send_command_shortcut(_CMD_C_DOWN)


def _send_command_shortcut(keycode: int) -> bool:
    if not _ax_is_trusted():
        from core.logger import log_warning
        log_warning("自动复制/粘贴需要辅助功能权限；内容仍保留在剪贴板，可手动粘贴", "Clipboard")
        return False
    try:
        try:
            _post_key_event(_CMD_KEY, True, command=True)
            _post_key_event(keycode, True, command=True)
        finally:
            try:
                _post_key_event(keycode, False, command=True)
            finally:
                _post_key_event(_CMD_KEY, False)
        return True
    except Exception as exc:
        from core.logger import log_exception
        log_exception(exc, "macOS 复制/粘贴快捷键")
        return False


def release_modifiers() -> None:
    """macOS 无 keybd_event 全局按键状态注入；发送前不依赖此步骤，
    保持空实现以兼容调用点。"""
    return None


class MacOSClipboardBackend(ClipboardBackend):
    """macOS 剪贴板后端。"""

    @staticmethod
    def activate_target(target: int) -> bool:
        from platforms import get_platform_backend
        return get_platform_backend().windows.set_foreground(target)

    @staticmethod
    def send_cmd_v() -> bool:
        return send_cmd_v()

    def copy_image(self, image: QImage, file_reference: Optional[str] = None) -> None:
        clipboard = QGuiApplication.clipboard()
        if file_reference:
            mime = QMimeData()
            mime.setImageData(image)
            mime.setUrls([QUrl.fromLocalFile(file_reference)])
            clipboard.setMimeData(mime)
        else:
            clipboard.setImage(image)

    # ── 粘贴（焦点归还 + Command+V）──

    def paste_to_target(self, target: object) -> None:
        """target 为前台应用 PID（macOS 前台句柄=PID）或 None。"""
        if not target:
            _notify_paste_failure()
            return
        _activate_then_paste(target, 0)


def _foreground_is_own_process() -> bool:
    from platforms import get_platform_backend
    handle = get_platform_backend().windows.get_foreground_handle()
    if not handle:
        return False
    return int(handle) == get_platform_backend().windows.current_pid()


def _send_paste():
    release_modifiers()
    if not _ax_is_trusted():
        # 没有辅助功能权限时 CGEventPost 根本不会生效，这时再报"目标窗口已关闭"
        # 只会误导用户；必须直接指出缺的是哪个系统权限。
        _notify_paste_failure("permission")
        return
    if not send_cmd_v():
        _notify_paste_failure("permission")


def _send_paste_to_foreground():
    if not _foreground_is_own_process():
        _send_paste()


def _activate_then_paste(pid: int, attempt: int):
    from platforms import get_platform_backend
    backend = get_platform_backend()

    if pid == backend.windows.current_pid() or not backend.windows.is_alive(pid):
        _notify_paste_failure()
        return

    if backend.windows.get_foreground_handle() == pid:
        if not backend.windows.matches_paste_target(pid):
            _notify_paste_failure()
            return
        _send_paste()
        return

    if attempt >= _ACTIVATE_MAX_ATTEMPTS:
        _notify_paste_failure()
        return

    backend.windows.set_foreground(pid)
    QTimer.singleShot(_ACTIVATE_RETRY_MS, lambda: _activate_then_paste(pid, attempt + 1))


def _notify_paste_failure(reason: str = "target"):
    """提示自动粘贴失败。reason="permission" 表示缺辅助功能权限。"""
    from core.logger import log_warning
    from PySide6.QtWidgets import QApplication, QMessageBox

    # 没授权时，卡住自动粘贴的可能是"拿不到目标窗口"或"按键被系统吞掉"，
    # 但真正的原因是辅助功能权限；这时报"目标窗口已关闭"只会让用户白找一圈。
    if reason != "permission" and not _ax_is_trusted():
        reason = "permission"

    if reason == "permission":
        message = (
            "自动粘贴需要「辅助功能」权限。\n\n"
            "请在 系统设置 → 隐私与安全性 → 辅助功能 中允许“积磊截图”，"
            "然后重启应用。\n\n内容仍在剪贴板中，可以先手动粘贴（Command+V）。"
        )
        log_warning("自动粘贴缺少辅助功能权限", "Clipboard")
    else:
        message = "目标窗口已关闭或无法恢复焦点，已停止自动粘贴。内容仍在剪贴板中，请切到目标窗口手动粘贴。"
        log_warning(message, "Clipboard")

    if QApplication.instance() is not None:
        # Non-modal and retained by QApplication: never block an input callback.
        app = QApplication.instance()
        box = QMessageBox(QMessageBox.Icon.Warning, "积磊截图", message)
        box.setAttribute(Qt.WA_DeleteOnClose)
        if reason == "permission":
            open_btn = box.addButton("打开系统设置", QMessageBox.ButtonRole.ActionRole)
            open_btn.clicked.connect(_open_accessibility_settings)
        app._paste_failure_dialog = box
        box.open()


def _open_accessibility_settings():
    try:
        from platforms import get_platform_backend
        get_platform_backend().permissions.open_system_settings("accessibility")
    except Exception:
        pass
