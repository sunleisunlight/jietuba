# -*- coding: utf-8 -*-
"""Application-wide light/dark appearance management.

This module intentionally does not manage screenshot accent and mask colours;
those remain in :mod:`core.theme`.  UIThemeManager owns only semantic colours
used by application windows and native Qt widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


class UIThemeMode(str, Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"

    @classmethod
    def coerce(cls, value) -> "UIThemeMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.SYSTEM


@dataclass(frozen=True)
class UIThemeTokens:
    mode: UIThemeMode
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    window: str
    window_top: str
    window_bottom: str
    surface: str
    surface_strong: str
    surface_subtle: str
    surface_hover: str
    text: str
    text_muted: str
    text_disabled: str
    border: str
    border_hover: str
    window_border: str
    input_background: str
    popup_background: str
    popup_hover: str
    separator: str
    switch_off: str
    selected_text: str = "#FFFFFF"

    @property
    def is_dark(self) -> bool:
        return self.mode is UIThemeMode.DARK


# 积磊品牌主色（与官网 --brand 一致）：#FF5A1F，渐变 #FF7A3D → #E8430C
_COMMON = {
    "accent": "#FF5A1F",
    "accent_hover": "#E84B12",
    "accent_pressed": "#D23E0A",
}

LIGHT_TOKENS = UIThemeTokens(
    mode=UIThemeMode.LIGHT,
    **_COMMON,
    accent_soft="#FFF1EA",
    window="#F3EDE7",
    window_top="#F9F4EF",
    window_bottom="#EAE1D9",
    surface="rgba(255, 255, 255, 0.92)",
    surface_strong="rgba(255, 255, 255, 0.98)",
    surface_subtle="rgba(252, 248, 245, 0.88)",
    surface_hover="#FFFFFF",
    text="#1F1B18",
    text_muted="#6E665F",
    text_disabled="#A9A098",
    border="rgba(74, 56, 42, 0.18)",
    border_hover="rgba(210, 80, 25, 0.42)",
    window_border="#D4C8BC",
    input_background="#FFFFFF",
    popup_background="#FFFFFF",
    popup_hover="#FFF4EE",
    separator="rgba(80, 60, 45, 0.12)",
    switch_off="#C9C0B8",
)

DARK_TOKENS = UIThemeTokens(
    mode=UIThemeMode.DARK,
    **_COMMON,
    accent_soft="#4A2A1C",
    window="#221E1A",
    window_top="#2A2520",
    window_bottom="#1D1A17",
    surface="rgba(38, 34, 30, 0.96)",
    surface_strong="rgba(44, 40, 36, 0.99)",
    surface_subtle="rgba(32, 29, 26, 0.92)",
    surface_hover="#38312B",
    text="#F5F1EC",
    text_muted="#B3AAA1",
    text_disabled="#787069",
    border="rgba(255, 255, 255, 0.10)",
    border_hover="rgba(255, 138, 90, 0.42)",
    window_border="#3E3731",
    input_background="#2C2824",
    popup_background="#2A2622",
    popup_hover="#37302A",
    separator="rgba(255, 255, 255, 0.09)",
    switch_off="#5E564E",
)


class UIThemeManager(QObject):
    """Resolve, persist and apply the effective application appearance."""

    theme_changed = Signal(object)
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self._application: Optional[QApplication] = None
        self._mode = UIThemeMode.SYSTEM
        self._effective_mode = UIThemeMode.LIGHT
        self._system_signal_connected = False

    def init(self, config_manager=None, application=None):
        self._config = config_manager
        app = application or QApplication.instance()
        self._application = app if isinstance(app, QApplication) else None
        saved = (
            config_manager.get_app_setting("ui_theme_mode", "system")
            if config_manager is not None
            else "system"
        )
        self._mode = UIThemeMode.coerce(saved)
        self._connect_system_theme()
        self.apply(force=True)
        return self

    @property
    def mode(self) -> UIThemeMode:
        return self._mode

    @property
    def effective_mode(self) -> UIThemeMode:
        return self._effective_mode

    @property
    def is_dark(self) -> bool:
        return self._effective_mode is UIThemeMode.DARK

    @property
    def tokens(self) -> UIThemeTokens:
        return DARK_TOKENS if self.is_dark else LIGHT_TOKENS

    def set_mode(self, mode, persist: bool = True):
        normalized = UIThemeMode.coerce(mode)
        changed = normalized is not self._mode
        self._mode = normalized
        if persist and self._config is not None:
            self._config.set_app_setting("ui_theme_mode", normalized.value)
        self.apply(force=changed)
        if changed:
            self.mode_changed.emit(normalized.value)

    def apply(self, force: bool = False):
        effective = self._resolve_effective_mode()
        changed = effective is not self._effective_mode
        self._effective_mode = effective
        if not (force or changed):
            return

        if self._application is not None:
            self._application.setProperty("uiTheme", effective.value)
            self._application.setPalette(self.build_palette(self.tokens))
            self._application.setStyleSheet(
                self._build_global_stylesheet(self.tokens)
            )

        self.theme_changed.emit(self.tokens)

    def _resolve_effective_mode(self) -> UIThemeMode:
        if self._mode is not UIThemeMode.SYSTEM:
            return self._mode
        hints = QGuiApplication.styleHints()
        if hints is not None and hasattr(hints, "colorScheme"):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return UIThemeMode.DARK
            if scheme == Qt.ColorScheme.Light:
                return UIThemeMode.LIGHT

        # Some remote-desktop and older platform plugins report Unknown.
        app = self._application or QApplication.instance()
        if app is not None:
            window = app.palette().color(QPalette.ColorRole.Window)
            return (
                UIThemeMode.DARK
                if window.lightness() < 128
                else UIThemeMode.LIGHT
            )
        return UIThemeMode.LIGHT

    def _connect_system_theme(self):
        if self._system_signal_connected:
            return
        hints = QGuiApplication.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None) if hints else None
        if signal is not None:
            signal.connect(self._on_system_theme_changed)
            self._system_signal_connected = True

    def _on_system_theme_changed(self, _scheme):
        if self._mode is UIThemeMode.SYSTEM:
            self.apply()

    @staticmethod
    def build_palette(t: UIThemeTokens) -> QPalette:
        palette = QPalette()
        normal = QPalette.ColorGroup.Normal
        inactive = QPalette.ColorGroup.Inactive

        roles = {
            QPalette.ColorRole.Window: t.window,
            QPalette.ColorRole.WindowText: t.text,
            QPalette.ColorRole.Base: t.input_background,
            QPalette.ColorRole.AlternateBase: t.surface_subtle,
            QPalette.ColorRole.ToolTipBase: t.popup_background,
            QPalette.ColorRole.ToolTipText: t.text,
            QPalette.ColorRole.Text: t.text,
            QPalette.ColorRole.Button: t.surface_strong,
            QPalette.ColorRole.ButtonText: t.text,
            QPalette.ColorRole.BrightText: "#FFFFFF",
            QPalette.ColorRole.Link: t.accent,
            QPalette.ColorRole.Highlight: t.accent,
            QPalette.ColorRole.HighlightedText: t.selected_text,
            QPalette.ColorRole.PlaceholderText: t.text_muted,
            QPalette.ColorRole.Mid: t.border_hover,
            QPalette.ColorRole.Dark: t.window_border,
        }
        for group in (normal, inactive):
            for role, value in roles.items():
                palette.setColor(group, role, QColor(value))

        disabled = QPalette.ColorGroup.Disabled
        for role, value in roles.items():
            palette.setColor(disabled, role, QColor(value))
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
            QPalette.ColorRole.PlaceholderText,
        ):
            palette.setColor(disabled, role, QColor(t.text_disabled))
        return palette

    @staticmethod
    def _build_global_stylesheet(t: UIThemeTokens) -> str:
        # Keep this intentionally small.  Feature windows with their own theme
        # (for example Clipboard) remain free to override it locally.
        return f"""
            QToolTip {{
                color: {t.text};
                background-color: {t.popup_background};
                border: 1px solid {t.border_hover};
                padding: 4px 7px;
            }}
            QMenu {{
                color: {t.text};
                background-color: {t.popup_background};
                border: 1px solid {t.border};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {t.text};
                background-color: transparent;
                padding: 6px 28px 6px 26px;
                margin: 1px 0;
            }}
            QMenu::item:selected {{
                color: {t.text};
                background-color: {t.popup_hover};
            }}
            QMenu::item:disabled {{
                color: {t.text_disabled};
                background-color: transparent;
            }}
            QMenu::separator {{
                height: 1px;
                background: {t.separator};
                margin: 4px 7px;
            }}
        """


_manager: Optional[UIThemeManager] = None


def get_ui_theme() -> UIThemeManager:
    global _manager
    if _manager is None:
        _manager = UIThemeManager()
    return _manager
