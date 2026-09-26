# -*- mode: python ; coding: utf-8 -*-
"""Jietuba macOS 打包 spec（PyInstaller onedir + .app bundle）。

用法：
    python build_macos.py            # 或
    pyinstaller jietuba_macos.spec --noconfirm

产物：dist/Jietuba.app（windowed，Apple Silicon arm64）
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs
import glob
import os
import sys
import sysconfig

block_cipher = None

# ── 版本唯一源：main/main_app.py 的 APP_VERSION（AGENTS.md 版本规则）──
# spec 由 PyInstaller 执行，SPECPATH 指向本文件所在目录（仓库根）。
_SPEC_DIR = globals().get("SPECPATH") or os.getcwd()
sys.path.insert(0, os.path.join(_SPEC_DIR, "scripts"))
from version_utils import read_app_version  # noqa: E402

APP_VERSION = read_app_version()

# ── 数据资源 ──
datas = [
    ("svg", "svg"),
    ("main/translations", "translations"),
]

# ── 二进制依赖 ──
binaries = []

# ppocr_rust（Rust + ort 的 PP-OCR 引擎）在 Mac 上与 Windows 功能对齐，是正式
# 必需项。除扩展自身外还必须把 ONNX Runtime 动态库一起带进 .app，否则源码环境
# 能跑、真实 .app 里 import ppocr_rust 会失败。
try:
    binaries += collect_dynamic_libs("ppocr_rust")
except Exception as _exc:  # pragma: no cover - 打包环境分支
    print("collect_dynamic_libs('ppocr_rust') 跳过:", _exc)


def _find_onnxruntime_dylibs():
    """定位本机 ort/ONNX Runtime 动态库（静态链接时返回空列表）。"""
    patterns = []
    for key in ("purelib", "platlib"):
        base = sysconfig.get_paths().get(key)
        if base:
            patterns.append(os.path.join(base, "**", "libonnxruntime*.dylib"))
    # maturin 本地构建时 ort-sys 的产物落在 cargo target 目录
    patterns.append(os.path.join(_SPEC_DIR, "rust_libs", "target", "**", "libonnxruntime*.dylib"))
    # ort-sys 下载缓存
    patterns.append(os.path.expanduser("~/.cache/ort/**/libonnxruntime*.dylib"))
    found = set()
    for pattern in patterns:
        found.update(glob.glob(pattern, recursive=True))
    return sorted(found)


_ort_dylibs = _find_onnxruntime_dylibs()
for _dylib in _ort_dylibs:
    binaries.append((_dylib, "."))
print("onnxruntime dylibs:", _ort_dylibs or "(静态链接/无外部 dylib)")

# PySide6 插件：cocoa 平台、SVG 与图片格式
datas += collect_data_files("PySide6", includes=["plugins/**"])

# ── OCR 模型：Mac 正式构建必需（与 Windows 功能对齐），缺失即构建失败 ──
OCR_MODELS = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx")
for _model in OCR_MODELS:
    _model_path = os.path.join(_SPEC_DIR, "models", _model)
    if not os.path.isfile(_model_path):
        raise SystemExit(
            f"缺少 OCR 模型 {_model_path}；Mac 正式构建要求 OCR 与 Windows 对齐，"
            "模型不是可选项。"
        )
    datas.append((_model_path, "models"))

# ── 隐藏导入 ──
hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtXml",
    "pyclipboard",
    "longstitch",
    "gifrecorder",
    "ppocr_rust",
    "zxingcpp",
    "PIL",
    "PIL.Image",
    "mss",
    "mss.base",
    "mss.exception",
    "mss.factory",
    "mss.models",
    "mss.screenshot",
    "mss.tools",
    "pynput",
    "darkdetect",
    "platforms",
]
def _mac_module(name):
    return not any(part in {"_win32", "_xorg", "_uinput", "win32", "xorg", "uinput", "linux", "windows"}
                   for part in name.split("."))


hiddenimports += collect_submodules("pynput", filter=_mac_module)
hiddenimports += collect_submodules("mss", filter=_mac_module)

# ── 排除（Windows 专用/无关大包）──
excludes = [
    "mss.linux", "mss.windows",
    "pynput._util.win32", "pynput._util.xorg", "pynput._util.uinput",
    "pynput.keyboard._win32", "pynput.keyboard._xorg", "pynput.keyboard._uinput",
    "pynput.mouse._win32", "pynput.mouse._xorg",
    "av",
    "matplotlib",
    "scipy",
    "pandas",
    "torch",
    "tensorflow",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "tkinter",
    "pytest",
    "IPython",
    "jupyter",
    "rapidocr",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "keyboard",
    "windows_media_ocr",
    "win32api",
    "win32con",
    "win32gui",
    "win32clipboard",
    "pywin32",
    "comtypes",
    "pythoncom",
    "win32com",
    "win32com.client",
    "win32com.server",
    "win32com.gen_py",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickTest",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtDesigner",
    "PySide6.QtTest",
    "PySide6.QtConcurrent",
    "PySide6.QtDBus",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQuick3D",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
]

a = Analysis(
    ["main/main_app.py"],
    pathex=["main"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jietuba",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Jietuba",
)

app = BUNDLE(
    coll,
    name="Jietuba.app",
    icon="assets/Jietuba.icns",
    bundle_identifier="cc.jilei.jietuba",
    info_plist={
        "CFBundleIdentifier": "cc.jilei.jietuba",
        "CFBundleName": "Jietuba",
        "CFBundleDisplayName": "截图吧",
        "CFBundleExecutable": "Jietuba",
        "CFBundleIconFile": "Jietuba.icns",
        "CFBundlePackageType": "APPL",
        # 版本来自 main/main_app.py 的 APP_VERSION（禁止在此写死）
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleInfoDictionaryVersion": "6.0",
        # GIF 录制依赖 ScreenCaptureKit（macOS 12.3+），最低系统版本必须与
        # 真实实现一致，不能声称支持实际跑不起来的更低版本。
        "LSMinimumSystemVersion": "12.3",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSScreenCaptureUsageDescription": "用于截图、区域捕获和屏幕录制。",
    },
)
