# -*- coding: utf-8 -*-
"""Windows 剪贴板后端 — Win32 CF_DIBV5/PNG/CF_HDROP 写入 + Ctrl+V 粘贴。

从 core/clipboard_utils.py 与 clipboard/controllers/paste_keystroke.py
平移而来，逻辑保持不变。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import io
import struct
from typing import Optional

from PySide6.QtCore import QBuffer, QIODeviceBase
from PySide6.QtGui import QImage

from ..base.clipboard import ClipboardBackend

_CLIPBOARD_WRITE_LOCK = None  # 惰性创建，避免无 Qt 环境导入崩溃


def _lock():
    global _CLIPBOARD_WRITE_LOCK
    if _CLIPBOARD_WRITE_LOCK is None:
        import threading
        _CLIPBOARD_WRITE_LOCK = threading.Lock()
    return _CLIPBOARD_WRITE_LOCK


# ── 剪贴板写入 ────────────────────────────────────────────────

def _build_dibv5(image: QImage) -> bytes:
    """将 QImage 转为 BITMAPV5HEADER + 32 位 BGRA 像素数据（bottom-up）。"""
    img = image.convertToFormat(QImage.Format.Format_ARGB32)
    w = img.width()
    h = img.height()
    stride = w * 4
    pixel_size = stride * h

    header = io.BytesIO()
    header.write(struct.pack('<I', 124))
    header.write(struct.pack('<i', w))
    header.write(struct.pack('<i', h))
    header.write(struct.pack('<H', 1))
    header.write(struct.pack('<H', 32))
    header.write(struct.pack('<I', 3))            # BI_BITFIELDS
    header.write(struct.pack('<I', pixel_size))
    header.write(struct.pack('<i', 0))
    header.write(struct.pack('<i', 0))
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 0x00FF0000))   # RedMask
    header.write(struct.pack('<I', 0x0000FF00))   # GreenMask
    header.write(struct.pack('<I', 0x000000FF))   # BlueMask
    header.write(struct.pack('<I', 0xFF000000))   # AlphaMask
    header.write(struct.pack('<I', 0x73524742))   # LCS_sRGB
    header.write(b'\x00' * 36)
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 4))            # LCS_GM_IMAGES
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 0))
    header.write(struct.pack('<I', 0))

    header_bytes = header.getvalue()
    assert len(header_bytes) == 124

    flipped = img.mirrored(False, True)
    bits = flipped.bits()
    return header_bytes + bytes(bits)


def _build_png(image: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODeviceBase.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG", 50)
    buf.close()
    return bytes(buf.data())


def _build_hdrop(path: str) -> bytes:
    name = path.encode("utf-16-le") + b"\x00\x00" + b"\x00\x00"
    header = struct.pack("<Iiiii", 20, 0, 0, 0, 1)
    return header + name


class WindowsClipboardBackend(ClipboardBackend):
    """Windows 剪贴板后端。"""

    def copy_image(self, image: QImage, file_reference: Optional[str] = None) -> None:
        import win32clipboard

        dibv5_data = _build_dibv5(image)
        png_data = _build_png(image)
        fmt_png = win32clipboard.RegisterClipboardFormat("PNG")
        hdrop_data = _build_hdrop(file_reference) if file_reference else None

        with _lock():
            win32clipboard.OpenClipboard(0)
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(fmt_png, png_data)
                win32clipboard.SetClipboardData(17, dibv5_data)  # CF_DIBV5
                if hdrop_data is not None:
                    win32clipboard.SetClipboardData(15, hdrop_data)  # CF_HDROP
            finally:
                win32clipboard.CloseClipboard()

    # ── 粘贴（焦点归还 + Ctrl+V）──

    def paste_to_target(self, target: object) -> None:
        """Windows 实现见 paste_keystroke（保持原有语义）。"""
        from ...clipboard.controllers.paste_keystroke import paste_to_target as _win_paste
        _win_paste(target)


# ── Win32 剪贴板忙重试（供 clipboard_utils 复用）───────────────

def run_clipboard_write_with_retry(operation, path_name: str) -> None:
    """Windows 剪贴板被占用时自动重试（历史实现）。"""
    import time as _time

    _CLIPBOARD_WRITE_RETRY_DELAYS = (0.0, 0.02, 0.05, 0.1, 0.2, 0.35)
    _CLIPBOARD_BUSY_HRESULT = -2147221040  # 0x800401D0 = CLIPBRD_E_CANT_OPEN

    last_exc = None
    total_attempts = len(_CLIPBOARD_WRITE_RETRY_DELAYS)

    for attempt_index, delay in enumerate(_CLIPBOARD_WRITE_RETRY_DELAYS, start=1):
        if delay > 0:
            _time.sleep(delay)
        try:
            operation()
            return
        except Exception as exc:
            last_exc = exc
            hresult = getattr(exc, "hresult", None)
            args = getattr(exc, "args", ())
            busy = (
                hresult == _CLIPBOARD_BUSY_HRESULT
                or (args and args[0] == _CLIPBOARD_BUSY_HRESULT)
                or (isinstance(args, tuple) and args and isinstance(args[0], tuple)
                    and args[0] and args[0][0] == _CLIPBOARD_BUSY_HRESULT)
            )
            if not busy or attempt_index == total_attempts:
                raise

    if last_exc is not None:
        raise last_exc
