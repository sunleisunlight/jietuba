# -*- mode: python ; coding: utf-8 -*-
"""Jietuba macOS 打包 spec（PyInstaller onedir + .app bundle）。

用法：
    python build_macos.py            # 或
    pyinstaller jietuba_macos.spec --noconfirm

产物：dist/Jietuba.app（windowed，Apple Silicon arm64）
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# ── 数据资源 ──
datas = [
    ("svg", "svg"),
    ("main/translations", "translations"),
    ("models", "models"),            # OCR 模型（随包，Resources/ 下）
]

# PySide6 插件：cocoa 平台、SVG 与图片格式
datas += collect_data_files("PySide6", includes=["plugins/**"])

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
    "av",
    "platforms",
]
hiddenimports += collect_submodules("pynput")
hiddenimports += collect_submodules("mss")

# ── 排除（Windows 专用/无关大包）──
excludes = [
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
    binaries=[],
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
        "CFBundleShortVersionString": "2.0.6",
        "CFBundleVersion": "206",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSScreenCaptureUsageDescription": "用于截图、区域捕获和屏幕录制。",
    },
)
