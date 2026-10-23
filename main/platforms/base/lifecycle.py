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

    def restart_app(self) -> bool:
        """重启本应用；不支持返回 False。

        macOS 的屏幕录制 / 辅助功能属 TCC 权限，在系统设置里打开后要等进程
        重启才生效，所以权限引导里需要这条真正的"重启"路径。
        """
        return False

    def create_executable_shortcut(self, destination, target, *, arguments="", working_directory=None):
        """Create a native executable launcher; raise if unsupported or failed."""
        raise NotImplementedError("This platform does not use executable shortcuts")

    @abstractmethod
    def autostart_enabled(self):
        """Read this application's login registration only."""

    @abstractmethod
    def set_autostart(self, enabled):
        """Persist registration; raise on failure (never report fake success)."""
