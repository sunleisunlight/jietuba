# -*- coding: utf-8 -*-
"""macOS 全局热键后端 — Carbon RegisterEventHotKey（ctypes 直接调用）。

为什么选 Carbon：
  - RegisterEventHotKey 是系统级全局热键注册，不要求辅助功能/输入监控权限；
  - CGEventTap 方案需要辅助功能权限且是低层事件监听；
  - pynput 键盘监听同样需要输入监控权限，且不适合做"注册式"热键。
Qt 应用的主线程运行 Cocoa run loop，Carbon 事件处理器由该 run loop 派发，
回调落在主线程，可以直接安全调用 Python 回调。

键位约定：Windows 风格字符串 ctrl/alt/shift/win 在 macOS 映射为
control/option/shift/command；"win" 键映射为 Command。
"""
from __future__ import annotations

import ctypes
from ctypes import Structure, c_int32, c_uint32, c_void_p, byref, sizeof
from typing import Callable, Dict, Optional

from ..base.hotkey import GlobalHotkeyBackend

# ── Carbon 常量 ──────────────────────────────────────────────

kEventClassKeyboard = 0x6B657962  # 'keyb'
kEventHotKeyPressed = 1
kEventHotKeyReleased = 2
kEventParamDirectObject = 0x2D2D2D2D  # '----'
typeEventHotKeyID = 0x686B6964         # 'hkid'

noErr = 0
eventHotKeyExistsErr = -9878

cmdKey = 0x0100
shiftKey = 0x0200
optionKey = 0x0800
controlKey = 0x1000

# 标准 macOS 虚拟键码（HIToolbox Events.h）
_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37,
    "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44,
    "n": 45, "m": 46, ".": 47, "`": 50, "esc": 53, "space": 49,
    "enter": 36, "return": 36, "tab": 48, "delete": 51, "backspace": 51,
    "forwarddelete": 117, "home": 115, "end": 119, "pageup": 116,
    "pagedown": 121, "help": 114,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103,
    "f12": 111, "f13": 105, "f14": 107, "f15": 113, "f16": 106,
    "f17": 64, "f18": 79, "f19": 80, "f20": 90,
    "printscreen": 105, "scrolllock": 107, "pause": 113,
    "numlock": 71, "capslock": 57, "kp0": 82, "kp1": 83, "kp2": 84,
    "kp3": 85, "kp4": 86, "kp5": 87, "kp6": 88, "kp7": 89,
    "kp8": 91, "kp9": 92, "kpdecimal": 65, "kpdivide": 75,
    "kpmultiply": 67, "kpsubtract": 78, "kpplus": 69, "kpequal": 81,
}


def _carbon_framework():
    # GetApplicationEventTarget / InstallEventHandler / RegisterEventHotKey
    # 属于 HIToolbox/Carbon，ApplicationServices 不导出这些符号；
    # Carbon.framework 是传统伞形框架，同时导出 HIToolbox 与 CarbonCore 符号。
    return ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")


class _EventHotKeyID(Structure):
    _fields_ = [("signature", c_uint32), ("id", c_uint32)]


class _EventTypeSpec(Structure):
    _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]


_EventHandlerProcPtr = ctypes.CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)


class MacOSHotkeyBackend(GlobalHotkeyBackend):
    """macOS Carbon 热键后端。"""

    def __init__(self):
        self._id_to_callback: Dict[int, Callable] = {}
        self._id_to_ref: Dict[int, c_void_p] = {}
        self._handler_ref = None
        self._installed = False
        self._framework = None
        self._app_target = None
        self._handler_callback = None  # 防 GC

    # ── 内部：解析 ──

    @staticmethod
    def parse_hotkey(hotkey: str):
        """返回 (keycode, modifiers)；非法返回 None。"""
        if not hotkey or not isinstance(hotkey, str):
            return None
        parts = [p.strip().lower() for p in hotkey.split('+') if p.strip()]
        if not parts:
            return None

        mods = 0
        key = None
        for p in parts:
            if p in ("ctrl", "control"):
                mods |= controlKey
            elif p == "alt":
                mods |= optionKey
            elif p == "shift":
                mods |= shiftKey
            elif p in ("win", "meta", "super"):
                mods |= cmdKey
            else:
                key = p

        if not key:
            return None
        keycode = _KEYCODES.get(key)
        if keycode is None:
            return None
        return keycode, mods

    # ── 生命周期 ──

    def _ensure_installed(self) -> bool:
        if self._installed:
            return True
        try:
            fw = _carbon_framework()
            self._framework = fw

            fw.GetApplicationEventTarget.restype = c_void_p
            target = fw.GetApplicationEventTarget()
            if not target:
                return False
            self._app_target = target

            spec = _EventTypeSpec(kEventClassKeyboard, kEventHotKeyPressed)

            def _handler(_call_ref, _event_ref, _user_data):
                try:
                    hid = _EventHotKeyID()
                    fw.GetEventParameter.argtypes = [
                        c_void_p, c_uint32, c_uint32, ctypes.POINTER(c_uint32),
                        c_uint32, ctypes.POINTER(c_uint32), c_void_p,
                    ]
                    fw.GetEventParameter.restype = c_int32
                    result = fw.GetEventParameter(
                        _event_ref, kEventParamDirectObject, typeEventHotKeyID,
                        None, sizeof(_EventHotKeyID), None, byref(hid),
                    )
                    if result == noErr:
                        cb = self._id_to_callback.get(hid.id)
                        if cb:
                            try:
                                cb()
                            except Exception:
                                pass
                    return noErr
                except Exception:
                    return noErr

            self._handler_callback = _EventHandlerProcPtr(_handler)
            fw.InstallEventHandler.argtypes = [
                c_void_p, _EventHandlerProcPtr, c_uint32,
                ctypes.POINTER(_EventTypeSpec), c_void_p, ctypes.POINTER(c_void_p),
            ]
            fw.InstallEventHandler.restype = c_int32
            ref = c_void_p()
            result = fw.InstallEventHandler(
                target, self._handler_callback, 1, byref(spec), None, byref(ref),
            )
            if result != noErr:
                return False
            self._handler_ref = ref
            self._installed = True
            return True
        except Exception:
            return False

    def register(self, hotkey_id: int, hotkey_str: str, callback: Callable[[], None]) -> bool:
        parsed = self.parse_hotkey(hotkey_str)
        if parsed is None:
            return False
        keycode, mods = parsed
        if not self._ensure_installed():
            return False
        try:
            fw = self._framework
            hid = _EventHotKeyID(0x6A696554, hotkey_id)  # signature 'jieT'
            ref = c_void_p()
            fw.RegisterEventHotKey.argtypes = [
                c_uint32, c_uint32, _EventHotKeyID, c_void_p, c_uint32,
                ctypes.POINTER(c_void_p),
            ]
            fw.RegisterEventHotKey.restype = c_int32
            # inTarget 不能传 NULL（返回 paramErr -50），必须给应用事件目标
            result = fw.RegisterEventHotKey(
                keycode, mods, hid, self._app_target or c_void_p(), 0, byref(ref),
            )
            if result != noErr:
                return False
            self._id_to_callback[hotkey_id] = callback
            self._id_to_ref[hotkey_id] = ref
            return True
        except Exception:
            return False

    def unregister(self, hotkey_id: int) -> None:
        ref = self._id_to_ref.pop(hotkey_id, None)
        self._id_to_callback.pop(hotkey_id, None)
        if ref is not None and self._framework is not None:
            try:
                self._framework.UnregisterEventHotKey.argtypes = [c_void_p]
                self._framework.UnregisterEventHotKey.restype = c_int32
                self._framework.UnregisterEventHotKey(ref)
            except Exception:
                pass

    def unregister_all(self) -> None:
        for hid in list(self._id_to_ref.keys()):
            self.unregister(hid)

    def check_available(self, hotkey_str: str) -> bool:
        """探测是否可用：可解析即认为可注册（Carbon 无全局占用查询）。"""
        return self.parse_hotkey(hotkey_str) is not None
