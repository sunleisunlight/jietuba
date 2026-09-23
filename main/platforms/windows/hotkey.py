# -*- coding: utf-8 -*-
"""Windows 全局热键后端 — RegisterHotKey / WM_HOTKEY 原生实现。

从 core/shortcut_manager.py 平移而来，逻辑保持不变：
  - register：RegisterHotKey（键盘组合键）
  - native filter：拦截 WM_HOTKEY 消息
鼠标侧键 token（mouseback/mouseforward）不走 RegisterHotKey，
仍由 ShortcutManager 的 pynput 监听器处理，不在此注册。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QAbstractNativeEventFilter

from ..base.hotkey import GlobalHotkeyBackend

# Windows 常量
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# 进程内已注册集合（类级，供 check_available 判断重复）
_registered_keys_global: set = set()


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    """拦截 Windows WM_HOTKEY 消息，委托给回调。"""

    def __init__(self, id_to_callback: Dict[int, Callable]):
        super().__init__()
        self._id_to_callback = id_to_callback

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    hotkey_id = msg.wParam
                    cb = self._id_to_callback.get(hotkey_id)
                    if cb:
                        try:
                            cb()
                        except Exception:
                            pass
                        return True, 0
        except Exception:
            pass
        return False, 0


class WindowsHotkeyBackend(GlobalHotkeyBackend):
    """Windows 热键后端。"""

    def __init__(self):
        self._id_to_callback: Dict[int, Callable] = {}
        self._id_to_metadata: Dict[int, Tuple[int, int]] = {}
        self._next_hotkey_id = 1

    # ── 内部：字符串 → (mods, vk) ──

    @staticmethod
    def parse_hotkey(hotkey: str) -> Tuple[int, int]:
        """将 'ctrl+shift+a' 风格字符串解析为 (modifiers, vk)。"""
        if not hotkey or not isinstance(hotkey, str):
            raise ValueError("无效的热键字符串")

        parts = [p.strip().lower() for p in hotkey.split('+') if p.strip()]
        if not parts:
            raise ValueError("热键不能为空")

        mods = 0
        key = None

        for p in parts:
            if p in ("ctrl", "control"):
                mods |= MOD_CONTROL
            elif p == "alt":
                mods |= MOD_ALT
            elif p == "shift":
                mods |= MOD_SHIFT
            elif p in ("win", "meta", "super"):
                mods |= MOD_WIN
            else:
                key = p

        if not key:
            raise ValueError("缺少主键位")

        vk = None
        if len(key) == 1 and 'a' <= key <= 'z':
            vk = ord(key.upper())
        elif key.isdigit() and len(key) == 1:
            vk = ord(key)
        elif key.startswith('f') and key[1:].isdigit():
            n = int(key[1:])
            if 1 <= n <= 24:
                vk = 0x70 + (n - 1)
        elif key in ("printscreen", "prtsc"):
            vk = 0x2C
        elif key == "esc":
            vk = 0x1B
        elif key in ("`", "oem3", "backquote", "grave"):
            vk = 0xC0
        elif key in ("-", "minus"):
            vk = 0xBD
        elif key in ("=", "equals", "equal"):
            vk = 0xBB
        elif key in ("[", "lbracket"):
            vk = 0xDB
        elif key in ("]", "rbracket"):
            vk = 0xDD
        elif key in ("\\", "backslash"):
            vk = 0xDC
        elif key in (";", "semicolon"):
            vk = 0xBA
        elif key in ("'", "quote"):
            vk = 0xDE
        elif key in (",", "comma"):
            vk = 0xBC
        elif key in (".", "period"):
            vk = 0xBE
        elif key in ("/", "slash"):
            vk = 0xBF

        if vk is None:
            raise ValueError(f"不支持的键: {key}")

        mods |= MOD_NOREPEAT
        return mods, vk

    # ── 注册 / 注销 ──

    def register(self, hotkey_id: int, hotkey_str: str, callback: Callable[[], None]) -> bool:
        try:
            mods, vk = self.parse_hotkey(hotkey_str)
        except ValueError:
            return False
        try:
            if ctypes.windll.user32.RegisterHotKey(None, hotkey_id, mods, vk):
                self._id_to_callback[hotkey_id] = callback
                self._id_to_metadata[hotkey_id] = (mods, vk)
                _registered_keys_global.add((mods, vk))
                self._next_hotkey_id = max(self._next_hotkey_id, hotkey_id + 1)
                return True
            return False
        except Exception:
            return False

    def unregister(self, hotkey_id: int) -> None:
        try:
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        except Exception:
            pass
        meta = self._id_to_metadata.pop(hotkey_id, None)
        if meta:
            _registered_keys_global.discard(meta)
        self._id_to_callback.pop(hotkey_id, None)

    def unregister_all(self) -> None:
        for hid in list(self._id_to_callback.keys()):
            try:
                ctypes.windll.user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
            meta = self._id_to_metadata.pop(hid, None)
            if meta:
                _registered_keys_global.discard(meta)
        self._id_to_callback.clear()
        self._id_to_metadata.clear()

    def check_available(self, hotkey_str: str) -> bool:
        try:
            mods, vk = self.parse_hotkey(hotkey_str)
        except ValueError:
            return False
        if (mods, vk) in _registered_keys_global:
            return True
        try:
            test_id = 9999
            success = ctypes.windll.user32.RegisterHotKey(None, test_id, mods, vk)
            if success:
                ctypes.windll.user32.UnregisterHotKey(None, test_id)
                return True
            return False
        except Exception:
            return False

    def install_native_filter(self, app) -> Optional[object]:
        return _HotkeyEventFilter(self._id_to_callback)
