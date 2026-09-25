# -*- coding: utf-8 -*-
"""跨平台 import 测试：macOS 上不得因 Windows-only 依赖导致启动失败。"""
import sys
import importlib
import subprocess

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS import 隔离验证")
def test_windows_backend_import_does_not_touch_windll():
    """Windows 后端模块应可被 import（惰性），且不访问 ctypes.windll。

    （Windows 上本测试自动跳过；该模块真正的 Win32 调用只在 win32 平台执行。）
    """
    import ctypes

    assert not hasattr(ctypes, "windll") or sys.platform == "win32"

    # 关键业务模块在 macOS 上必须能 import
    for mod in (
        "capture.window_finder",
        "capture.uia_element_finder",
        "capture.capture_service",
        "platforms",
        "platforms.macos.window",
        "platforms.macos.accessibility",
        "platforms.macos.clipboard",
        "platforms.macos.hotkey",
        "platforms.windows.capture",   # Windows 后端文件存在（不破坏 Windows）
        "platforms.windows.hotkey",
        "platforms.windows.clipboard",
        "core.shortcut_manager",
        "settings.tool_settings",
    ):
        importlib.import_module(mod)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS import 隔离验证")
def test_main_app_imports_without_win32():
    """main_app.py 的核心导入链在 macOS 上不应引用 win32 模块。"""
    # 通过子进程验证：导入核心模块后 sys.modules 中不存在 win32 族
    code = """
import sys
from capture import window_finder, uia_element_finder, capture_service
from core import shortcut_manager, resource_manager
from settings import tool_settings
bad = [m for m in sys.modules if m.split('.')[0] in
       ('win32api','win32con','win32gui','win32clipboard','pywin32','comtypes')]
print('WIN32_MODULES:', bad)
assert not bad, f'Windows-only modules leaked: {bad}'
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "WIN32_MODULES: []" in r.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows import 验证")
def test_windows_sensitive_modules_import_on_windows():
    """Windows 上这些模块在 import 期就会跑 `if sys.platform == "win32"` 分支里的
    Win32 声明（ctypes.windll / argtypes / restype）。import 成功即代表这些声明
    有效——合并平台代码时最容易在这里踩到 `ctypes.LONG` 这类不存在的类型。"""
    for mod in (
        "clipboard.controllers.foreground_tracker",
        "clipboard.controllers.paste_keystroke",
        "core.platform_utils",
        "core.shortcut_manager",
        "platforms.windows.capture",
        "platforms.windows.hotkey",
        "platforms.windows.window",
        "platforms.windows.clipboard",
        "platforms.windows.accessibility",
        "capture.window_finder",
        "capture.uia_element_finder",
    ):
        importlib.import_module(mod)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS 依赖条件验证")
def test_requirements_conditional_deps():
    """requirements.txt 中 pywin32/comtypes 必须带 win32 条件标记。"""
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    text = (root / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("pywin32", "comtypes"):
        line = next((l for l in text.splitlines() if l.strip().startswith(pkg)), None)
        assert line is not None, f"{pkg} 未在 requirements.txt 中"
        assert "sys_platform" in line and "win32" in line, \
            f"{pkg} 缺少 win32 条件标记: {line}"
    # macOS 专属依赖应存在
    assert any("darwin" in l for l in text.splitlines()), "缺少 darwin 条件依赖"
