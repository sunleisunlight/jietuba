"""Portable shortcut tokens and the platform's Qt modifier convention.

Qt swaps Control/Meta on macOS: ControlModifier is the physical Command key.
Keep persisted ctrl portable; reserve lctrl for the physical Mac Control key.
"""
from PySide6.QtCore import Qt


class ShortcutConvention:
    def __init__(self, *, macos=False):
        self.macos = macos

    def storage(self, text):
        aliases = {"command": "ctrl", "cmd": "ctrl", "option": "alt"}
        aliases.update({"control": "lctrl", "win": "ctrl", "meta": "ctrl", "super": "ctrl"}
                       if self.macos else {"control": "ctrl", "lctrl": "ctrl", "meta": "win", "super": "win"})
        return "+".join(aliases.get(p.strip().lower(), p.strip().lower())
                        for p in (text or "").split("+"))

    def display(self, text):
        if not self.macos or not text:
            return text
        names = {"ctrl": "Command", "cmd": "Command", "command": "Command",
                 "win": "Command", "meta": "Command", "super": "Command",
                 "control": "Control", "lctrl": "Control", "alt": "Option",
                 "option": "Option", "shift": "Shift"}
        return "+".join(names.get(p.strip().lower(), p.strip()) for p in text.split("+"))

    def modifier_map(self):
        mod = Qt.KeyboardModifier
        result = {"ctrl": mod.ControlModifier, "alt": mod.AltModifier,
                  "shift": mod.ShiftModifier, "option": mod.AltModifier,
                  "cmd": mod.ControlModifier, "command": mod.ControlModifier}
        for token in ("win", "meta", "super"):
            result[token] = mod.ControlModifier if self.macos else mod.MetaModifier
        for token in ("control", "lctrl"):
            result[token] = mod.MetaModifier if self.macos else mod.ControlModifier
        return result

    def modifier_tokens(self, modifiers, key=None, *, released_key=None):
        pairs = ((Qt.ControlModifier, Qt.Key_Control, "ctrl"),
                 (Qt.ShiftModifier, Qt.Key_Shift, "shift"),
                 (Qt.AltModifier, Qt.Key_Alt, "alt"),
                 (Qt.MetaModifier, Qt.Key_Meta, "lctrl" if self.macos else "win"))
        return [token for flag, modifier_key, token in pairs
                if modifier_key != released_key and (modifiers & flag or key == modifier_key)]
