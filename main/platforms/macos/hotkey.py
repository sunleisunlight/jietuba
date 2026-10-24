# -*- coding: utf-8 -*-
"""macOS 全局热键后端 — Carbon RegisterEventHotKey（ctypes 直接调用）。

为什么选 Carbon：
  - RegisterEventHotKey 是系统级全局热键注册，不要求辅助功能/输入监控权限；
  - CGEventTap 方案需要辅助功能权限且是低层事件监听；
  - pynput 键盘监听同样需要输入监控权限，且不适合做"注册式"热键。
Qt 应用的主线程运行 Cocoa run loop，Carbon 事件处理器由该 run loop 派发，
回调落在主线程，可以直接安全调用 Python 回调。

键位约定：Windows 风格 ctrl 在 macOS 映射为 Command；lctrl/control
显式表示 Control；alt/shift/win 映射为 option/shift/command。
"""
from __future__ import annotations

import ctypes
from ctypes import Structure, c_int32, c_uint32, c_void_p, byref, sizeof
from typing import Callable, Dict

from ..base.hotkey import GlobalHotkeyBackend

# ── Carbon 常量 ──────────────────────────────────────────────

kEventClassKeyboard = 0x6B657962  # 'keyb'
# HIToolbox/CarbonEvents.h: 1/2 are raw key down/repeat, not hotkeys.
kEventHotKeyPressed = 5
kEventHotKeyReleased = 6
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
        self._id_to_binding = {}
        self._id_to_str: Dict[int, str] = {}
        self._handler_ref = None
        self._installed = False
        self._framework = None
        self._app_target = None
        self._handler_callback = None  # 防 GC

    def create_mouse_listener(self, on_trigger, suppressed_tokens):
        """pynput Mac Button 枚举不含 x1/x2，须读取原始 Quartz buttonNumber。"""
        from .permissions import _ax_is_trusted
        if not _ax_is_trusted():
            raise PermissionError("鼠标侧键需要辅助功能权限；授权后重新启用侧键或重启应用")
        import Quartz
        from pynput import mouse

        def intercept(event_type, event):
            if event_type not in (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp):
                return event
            button = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventButtonNumber)
            token = {3: "mouseback", 4: "mouseforward"}.get(button)
            if token is None:
                return event
            if event_type == Quartz.kCGEventOtherMouseDown:
                on_trigger(token)
            return None if token in suppressed_tokens() else event

        return mouse.Listener(darwin_intercept=intercept)

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
            # macOS 跨平台键位约定：Windows 配置里的 "ctrl" 在 Mac 上对应
            # Command(⌘) 键（Mac 的 Command ≈ Windows 的 Ctrl）；"win"/"meta"
            # 在 Mac 上也是 Command。Control(⌃) 需显式写 "lctrl" 才注册。
            if p == "ctrl":
                mods |= cmdKey
            elif p in ("lctrl", "control"):
                mods |= controlKey
            elif p in ("alt", "option"):
                mods |= optionKey
            elif p == "shift":
                mods |= shiftKey
            elif p in ("win", "meta", "super", "cmd", "command"):
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
                    try:
                        from core.logger import log_info, log_exception
                        log_info("Carbon 热键事件到达, hid.id=%s, getparam=%s" % (hid.id, result), "Hotkey")
                    except Exception:
                        pass
                    if result == noErr:
                        cb = self._id_to_callback.get(hid.id)
                        if cb:
                            try:
                                cb()
                            except Exception as e:
                                try:
                                    from core.logger import log_exception
                                    log_exception(e, "热键回调")
                                except Exception:
                                    pass
                    return noErr
                except Exception as e:
                    try:
                        from core.logger import log_exception
                        log_exception(e, "Carbon 热键 handler")
                    except Exception:
                        pass
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
        if hotkey_id in self._id_to_ref or parsed in self._id_to_binding.values():
            return False
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
            self._id_to_binding[hotkey_id] = parsed
            self._id_to_str[hotkey_id] = hotkey_str
            return True
        except Exception:
            return False

    def unregister(self, hotkey_id: int) -> None:
        ref = self._id_to_ref.pop(hotkey_id, None)
        self._id_to_callback.pop(hotkey_id, None)
        self._id_to_binding.pop(hotkey_id, None)
        self._id_to_str.pop(hotkey_id, None)
        if ref is not None and self._framework is not None:
            try:
                self._framework.UnregisterEventHotKey.argtypes = [c_void_p]
                self._framework.UnregisterEventHotKey.restype = c_int32
                self._framework.UnregisterEventHotKey(ref)
            except Exception:
                pass

    def ensure_registered(self) -> int:
        """自检并补注册被系统丢掉的 Carbon 热键，返回恢复数量。

        macOS 上 RegisterEventHotKey 的注册会在运行一段时间后偶发失效：
        注册表里看起来还在，但按键再也不派发（用户表现为"截了几张之后
        热键突然没反应"，只能重启应用）。这里用保留 id 试注册一次同一组合：
        Carbon 的占用判断是进程内的，返回 -9878 说明我们自己还占着；
        返回 noErr 说明注册真的丢了，立刻按原字符串重建。
        """
        if not self._installed or not self._id_to_binding:
            return 0
        fixed = 0
        for hotkey_id, parsed in list(self._id_to_binding.items()):
            keycode, mods = parsed
            if self._probe_registered(keycode, mods):
                continue
            callback = self._id_to_callback.get(hotkey_id)
            hotkey_str = self._id_to_str.get(hotkey_id)
            # 清掉三个登记表，让 register() 认为这个 id 是全新的
            self._id_to_ref.pop(hotkey_id, None)
            self._id_to_binding.pop(hotkey_id, None)
            self._id_to_callback.pop(hotkey_id, None)
            self._id_to_str.pop(hotkey_id, None)
            if callback is not None and hotkey_str is not None:
                if self.register(hotkey_id, hotkey_str, callback):
                    fixed += 1
        return fixed

    def _probe_registered(self, keycode: int, mods: int) -> bool:
        """本进程是否仍占着这个组合（用保留 id 试注册一下）。"""
        fw = self._framework
        if fw is None:
            return True
        probe = _EventHotKeyID(0x6A696554, 0x7FFFFFFE)
        ref = c_void_p()
        try:
            fw.RegisterEventHotKey.argtypes = [
                c_uint32, c_uint32, _EventHotKeyID, c_void_p, c_uint32,
                ctypes.POINTER(c_void_p),
            ]
            fw.RegisterEventHotKey.restype = c_int32
            result = fw.RegisterEventHotKey(
                keycode, mods, probe, self._app_target or c_void_p(), 0, byref(ref),
            )
            if result == eventHotKeyExistsErr:
                return True
            if result == noErr:
                fw.UnregisterEventHotKey.argtypes = [c_void_p]
                fw.UnregisterEventHotKey.restype = c_int32
                fw.UnregisterEventHotKey(ref)
                return False
            # 其它错误（比如 target 异常）先当作还在，下一轮再判断
            return True
        except Exception:
            return True

    def unregister_all(self) -> None:
        for hid in list(self._id_to_ref.keys()):
            self.unregister(hid)

    def check_available(self, hotkey_str: str) -> bool:
        """Probe Carbon registration, then release; own bindings remain editable."""
        parsed = self.parse_hotkey(hotkey_str)
        if parsed is None:
            return False
        if parsed in self._id_to_binding.values():
            return True
        probe_id = 0x7FFFFFFF
        if not self.register(probe_id, hotkey_str, lambda: None):
            return False
        self.unregister(probe_id)
        return True
