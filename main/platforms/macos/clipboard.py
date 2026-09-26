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

from PySide6.QtCore import QMimeData, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QImage

from ..base.clipboard import ClipboardBackend

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
            _send_paste_to_foreground()
            return
        _activate_then_paste(int(target), 0)


def _foreground_is_own_process() -> bool:
    from platforms import get_platform_backend
    handle = get_platform_backend().windows.get_foreground_handle()
    if not handle:
        return False
    return int(handle) == get_platform_backend().windows.current_pid()


def _send_paste():
    release_modifiers()
    send_cmd_v()


def _send_paste_to_foreground():
    if not _foreground_is_own_process():
        _send_paste()


def _activate_then_paste(pid: int, attempt: int):
    from platforms import get_platform_backend
    backend = get_platform_backend()

    if backend.windows.get_foreground_handle() == pid:
        _send_paste()
        return

    if attempt >= _ACTIVATE_MAX_ATTEMPTS:
        if _foreground_is_own_process():
            from core.logger import log_debug, T
            log_debug(T("目标应用 {pid} 未切到前台，放弃本次补按键", pid=pid), "Clipboard")
            return
        _send_paste()
        return

    backend.windows.set_foreground(pid)
    QTimer.singleShot(_ACTIVATE_RETRY_MS, lambda: _activate_then_paste(pid, attempt + 1))
