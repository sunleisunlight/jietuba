import sys

from .capture_service import CaptureService

# 平台分派：Windows 的 WindowFinder 依赖 win32gui/UIA；macOS 使用
# platforms.macos.window_finder。不要在 macOS 上 import 前者，否则仅
# `import capture` 就会触发 win32gui 缺失警告并污染启动日志。
if sys.platform == "win32":
    from .window_finder import WindowFinder, is_smart_selection_available
else:
    from platforms.macos.window_finder import (
        MacWindowFinder as WindowFinder,
        is_smart_selection_available,
    )

__all__ = ['CaptureService', 'WindowFinder', 'is_smart_selection_available']
 