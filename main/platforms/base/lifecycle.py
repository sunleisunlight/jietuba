"""Native application lifecycle contract; no UI/business duplication."""
from abc import ABC, abstractmethod


class LifecycleBackend(ABC):
    def show_on_manual_launch(self):
        return False

    def install_reopen_handler(self, callback):
        """Platforms without a Dock use the shared instance broker."""
        return None

    def activate(self):
        """Qt activation suffices unless the OS requires application activation."""
        return None

    def apply_window_icon(self, widget, icon):
        widget.setWindowIcon(icon)

    @abstractmethod
    def autostart_enabled(self):
        """Read this application's login registration only."""

    @abstractmethod
    def set_autostart(self, enabled):
        """Persist registration; raise on failure (never report fake success)."""
