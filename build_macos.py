#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""积磊截图 macOS 打包脚本。

流程：
  1. 准备 .icns（从 托盘.ico / assets 生成，若缺失）
  2. PyInstaller onedir 构建 dist/积磊截图.app（用户可见名称与 Windows 一致）
  3. 补齐 models/（Contents/Resources + Contents/MacOS 双位置，兼容旧查找路径）
  4. 本机可用证书签名（优先 Developer ID，其次 Apple Development，最后 ad-hoc）
  5. codesign 验证 + 关键资源存在性检查

用法：
  .venv/bin/python build_macos.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
VENV_PY = REPO / ".venv" / "bin" / "python"
DIST = REPO / "dist"
APP = DIST / "积磊截图.app"
SPEC = REPO / "jileiscreenshot_macos.spec"
ASSETS = REPO / "assets"
ICNS = ASSETS / "JileiScreenshot.icns"
ENTITLEMENTS = REPO / "packaging" / "entitlements.plist"

sys.path.insert(0, str(REPO / "scripts"))
from version_utils import read_app_version  # noqa: E402

# 版本唯一源：main/main_app.py 的 APP_VERSION（AGENTS.md 版本规则）
VERSION = read_app_version()

# PyInstaller / 图标生成都用这个解释器：优先项目虚拟环境，
# CI（无 .venv）等场景回退到当前解释器。
PYTHON = VENV_PY if VENV_PY.exists() else Path(sys.executable)

# OCR 模型：Mac 正式构建与 Windows 功能对齐，缺失即构建失败
MODELS = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx")

# otool 依赖检查时视为系统库的前缀（无需打包进 .app）
SYSTEM_DYLIB_PREFIXES = (
    "/usr/lib/",
    "/System/Library/",
    "/System/iOSSupport/",
    # Apple / 系统级 framework 安装位置（macOS runner 与真机均存在）
    "/Library/Frameworks/",
)


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def ensure_icns():
    """从 Windows 正式图标 ``托盘.ico`` 生成高清 macOS 图标。

    ICO 内含多个尺寸；不能取文件中的第一段 PNG（通常只有 16x16），否则
    macOS Finder/Dock 会把低分辨率图标放大成模糊的旧品牌图。每次构建都从
    Windows 资源的最大尺寸重新生成，确保两端始终使用同一份品牌图标。
    """
    ASSETS.mkdir(exist_ok=True)
    icon_png = REPO / "托盘.ico"
    tmp_png = "/tmp/jilei_screenshot_icon.png"
    iconset = "/tmp/jilei_screenshot.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset, exist_ok=True)

    code = f"""
from PIL import Image
ico = Image.open(r"{icon_png}")
largest = max(ico.ico.sizes(), key=lambda s: s[0] * s[1])
img = ico.ico.getimage(largest).convert("RGBA")
img.save(r"{tmp_png}")
for s in (16, 32, 64, 128, 256, 512, 1024):
    im = img.resize((s, s), Image.LANCZOS)
    im.save(f"{iconset}/icon_{{s}}x{{s}}.png")
    if s >= 32:
        im.save(f"{iconset}/icon_{{s//2}}x{{s//2}}@2x.png")
"""
    run([PYTHON, "-c", code])
    run(["iconutil", "-c", "icns", iconset, "-o", ICNS])
    print("icns ready:", ICNS)


def sign_app():
    """签名：优先 Developer ID Application，其次 Apple Development（本机固定
    cdhash，TCC 权限持久），最后 ad-hoc。"""
    identities = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    ).stdout
    ident = None
    # 1. Developer ID Application（分发用）
    for line in identities.splitlines():
        if "Developer ID Application" in line:
            ident = line.split('"')[1] if '"' in line else line.split()[1]
            break
    # 2. Apple Development（本机开发，cdhash 固定）
    if ident is None:
        for line in identities.splitlines():
            if "Apple Development" in line:
                ident = line.split('"')[1] if '"' in line else line.split()[1]
                break
    if ident is None:
        ident = "-"
        print("未找到可用签名证书，使用 ad-hoc (-；仅限本机运行)")
    print("使用签名身份:", ident)
    # 先清掉 PyInstaller 自带签名，再按顺序签：内部二进制 → 主可执行 → bundle
    run(["codesign", "--force", "--deep", "--sign", ident,
         "--options", "runtime",
         "--entitlements", ENTITLEMENTS, str(APP)])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(APP)])
    # 把固定签名要求打出来：macOS 的 TCC（屏幕录制/辅助功能）就是按它认 App 的。
    # ad-hoc 的固定要求是 cdhash，每构建一次就变一次，用户会被反复要求重新授权；
    # 证书签名的固定要求是 certificate leaf，重建后不变，授权才能一直沿用。
    req = subprocess.run(["codesign", "-d", "-r-", str(APP)], capture_output=True, text=True)
    requirement = (req.stdout + req.stderr).strip()
    print("签名要求:", requirement or "(未读取到)")
    if ident == "-" or "cdhash" in requirement:
        print("警告：ad-hoc 签名的固定要求是 cdhash，每次重建都会变，"
              "macOS 会把新构建当成另一个 App，屏幕录制 / 辅助功能授权必须重新授予。")
    # spctl：ad-hoc（无 Developer ID）时必然 rejected——这是预期的"本地可运行、
    # 未正式分发签名"状态，不视为失败；有 Developer ID 且完成公证后才应通过。
    sp = subprocess.run(
        ["spctl", "--assess", "--type", "execute", "-vv", str(APP)],
        capture_output=True, text=True,
    )
    if sp.returncode != 0:
        print("spctl:", sp.stdout.strip() or sp.stderr.strip())
        if ident == "-":
            print("（ad-hoc 签名：本地可运行；正式分发需 Developer ID + 公证）")
        elif "Developer ID Application" in ident:
            print("（Developer ID 已签名；正式分发仍需完成公证并装订）")
        else:
            print("（Apple Development 签名：适合本机调试；正式分发需 Developer ID + 公证）")
    else:
        print("spctl 通过")
    print("codesign done:", ident)


def ensure_resources():
    """OCR 模型：正式 Mac 构建必需（与 Windows 功能对齐），缺失直接失败。

    只保留一个权威位置 ``Contents/Resources/models``。运行时的查找顺序
    已在 ocr_manager._ppocr_rust_model_paths 中覆盖该路径；不再同时复制到
    Contents/MacOS/models，避免 29.5MB 模型在包里出现两份。
    """
    src_dir = REPO / "models"
    missing = [name for name in MODELS if not (src_dir / name).is_file()]
    if missing:
        print("!! 缺少 OCR 模型: %s" % ", ".join(missing))
        print("   仓库 models/ 必须包含: %s" % ", ".join(MODELS))
        print("   Mac 正式构建要求 OCR 与 Windows 对齐，模型不是可选项。")
        sys.exit(1)
    dst = APP / "Contents/Resources/models"
    dst.mkdir(parents=True, exist_ok=True)
    for name in MODELS:
        shutil.copy2(src_dir / name, dst / name)
    # 清掉历史遗留的第二份模型（旧构建脚本会写到这里）
    stale = APP / "Contents/MacOS/models"
    if stale.exists():
        shutil.rmtree(stale)
    print("models copied:", ", ".join(MODELS))


def thin_to_arm64():
    """把 universal2 Mach-O 瘦成 arm64。

    PySide6 的 macOS wheel 是 x86_64 + arm64 的 fat binary，而本项目 mac 目标
    只有 Apple Silicon。不瘦身等于把另一份架构白白装进 DMG。
    """
    import os as _os

    thinned = 0
    for path in APP.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        info = subprocess.run(
            ["lipo", "-info", str(path)], capture_output=True, text=True
        )
        if info.returncode != 0:
            continue
        if "x86_64" not in info.stdout or "arm64" not in info.stdout:
            continue
        tmp = path.with_name(path.name + ".arm64tmp")
        subprocess.run(
            ["lipo", "-thin", "arm64", str(path), "-output", str(tmp)],
            check=True, capture_output=True,
        )
        _os.replace(tmp, path)
        thinned += 1
    print("lipo thinned:", thinned, "Mach-O files")


def prune_qt_assets():
    """删除 .app 里用不到的 Qt 插件与翻译，减少安装包体积。

    PyInstaller 的 PySide6 收集器会带进整包插件；应用实际只用到 cocoa 平台、
    SVG/图片格式、mac 样式和 TLS。qml/designer/sqldrivers 等一律删掉。
    """
    keep_plugins = {
        "platforms/libqcocoa.dylib",
        "iconengines/libqsvgicon.dylib",
        "imageformats/libqgif.dylib",
        "imageformats/libqico.dylib",
        "imageformats/libqicns.dylib",
        "imageformats/libqjpeg.dylib",
        "imageformats/libqsvg.dylib",
        "imageformats/libqwebp.dylib",
        "styles/libqmacstyle.dylib",
        "tls/libqsecuretransportbackend.dylib",
        "networkinformation/libqscnetworkreachability.dylib",
    }
    keep_translations = {
        "qt_en.qm", "qt_ja.qm", "qt_ko.qm", "qt_zh_CN.qm", "qt_zh_TW.qm",
    }
    for plugins in APP.rglob("Qt/plugins"):
        for item in sorted(plugins.rglob("*"), reverse=True):
            if item.is_file():
                rel = item.relative_to(plugins).as_posix()
                if rel not in keep_plugins:
                    item.unlink()
            elif item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass
    for translations in APP.rglob("Qt/translations"):
        for item in translations.glob("*.qm"):
            if item.name not in keep_translations:
                item.unlink()

    # PyInstaller 的 PySide6 hook 会把 Qt/lib 下所有 framework 一起收进来。
    # 只保留业务真正依赖的模块；QtGui 依赖 QtDBus，因此 QtDBus 不能删。
    keep_frameworks = {
        "QtCore", "QtGui", "QtWidgets", "QtSvg", "QtSvgWidgets",
        "QtXml", "QtNetwork", "QtDBus",
    }
    for lib_dir in APP.rglob("Qt/lib"):
        for framework in lib_dir.glob("*.framework"):
            if framework.stem not in keep_frameworks:
                shutil.rmtree(framework)
    for pyside in APP.rglob("PySide6"):
        for binding in pyside.glob("*.abi3.so"):
            if binding.name.split(".", 1)[0] not in keep_frameworks:
                binding.unlink()
    # PyInstaller 会在 Contents/Frameworks 和 Contents/Resources 下为每个
    # framework 建同名符号链接。删掉 framework 后必须把这些链接一并删掉，
    # 否则 codesign --deep 会因为悬空链接直接失败（No such file or directory）。
    for p in APP.rglob("*"):
        if p.is_symlink() and not p.exists():
            p.unlink()
    print("Qt assets pruned")


def _app_contains(filename):
    """.app 内是否已存在同名文件（用于依赖是否被 PyInstaller 打包的判定）。"""
    return any(p.name == filename for p in APP.rglob(filename))


def check_native_dependencies():
    """用 otool 检查 .app 内原生扩展/动态库的非系统依赖是否都已打包。

    重点覆盖 ppocr_rust 在 macOS 上依赖的 ONNX Runtime dylib：若它只被链接
    但没进 .app，源码环境能跑、真实 .app 却会 import 失败。此处发现即判定构建
    失败，避免产出"看似构建成功但 OCR 不可用"的包。
    """
    ok = True
    binaries = []
    for sub in ("Contents/Frameworks", "Contents/Resources", "Contents/MacOS"):
        base = APP / sub
        if not base.exists():
            continue
        binaries += [p for p in base.rglob("*") if p.suffix in (".so", ".dylib")]
    for lib in binaries:
        out = subprocess.run(
            ["otool", "-L", str(lib)], capture_output=True, text=True
        )
        if out.returncode != 0:
            continue
        for line in out.stdout.splitlines()[1:]:
            dep = line.strip().split(" ", 1)[0]
            if not dep:
                continue
            if dep.startswith(SYSTEM_DYLIB_PREFIXES) or dep.startswith("/usr/lib"):
                continue
            # @rpath/@loader_path/@executable_path：由 PyInstaller 重写并随包携带，
            # 只需确认同名文件确实在 .app 内
            name = os.path.basename(dep)
            if not name:
                continue
            if not _app_contains(name):
                print(f"  [UNRESOLVED] {lib.name} -> {dep}")
                ok = False
    if ok:
        print("  [OK] native dependencies resolved inside .app")
    return ok


def verify_app():
    ok = True
    checks = [
        ("executable", APP / "Contents/MacOS/JileiScreenshot"),
        ("icon", APP / "Contents/Resources/JileiScreenshot.icns"),
        ("svg", APP / "Contents/Resources/svg/托盘.svg"),
        ("qm", APP / "Contents/Resources/translations/app_zh.qm"),
        ("det model (Resources)", APP / "Contents/Resources/models/PP-OCRv6_det_small.onnx"),
        ("rec model (Resources)", APP / "Contents/Resources/models/PP-OCRv6_rec_small.onnx"),
    ]
    for name, p in checks:
        exists = p.exists()
        ok = ok and exists
        print(f"  [{'OK' if exists else 'MISSING'}] {name}: {p}")
    # Info.plist 关键键 + 版本必须等于 APP_VERSION
    plist = APP / "Contents/Info.plist"
    if plist.exists():
        import plistlib
        with open(plist, "rb") as f:
            info = plistlib.load(f)
        for key in ("CFBundleIdentifier", "NSScreenCaptureUsageDescription",
                    "CFBundleShortVersionString", "CFBundleVersion"):
            print(f"  [{'OK' if key in info else 'MISSING'}] Info.plist {key} = {info.get(key)}")
        if info.get("CFBundleIdentifier") != "cc.jilei.jileiscreenshot":
            ok = False
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            if info.get(key) != VERSION:
                print(f"  !! Info.plist {key}={info.get(key)!r} != APP_VERSION={VERSION!r}")
                ok = False
    else:
        ok = False
    # Rust 扩展：Mac 与 Windows 功能对齐后 ppocr_rust 也是必需项
    for so, required in (("gifrecorder", True), ("longstitch", True),
                          ("pyclipboard", True), ("ppocr_rust", True)):
        found = list((APP / "Contents/Frameworks").rglob(f"{so}*.so"))
        found += list((APP / "Contents/Resources").rglob(f"{so}*.so"))
        tag = "OK" if found else "MISSING"
        print(f"  [{tag}] rust ext {so}: {found[0].name if found else ''}")
        if required:
            ok = ok and bool(found)
    ok = check_native_dependencies() and ok
    return ok


def main():
    # A bundled filename is not proof that dyld can load the extension.
    # Fail before touching the prior local build when native symbols are missing.
    run([PYTHON, "-c", "import gifrecorder, longstitch, pyclipboard, ppocr_rust; print('Native imports OK')"])
    ensure_icns()
    if APP.exists():
        shutil.rmtree(APP)
    if (DIST / "JileiScreenshot").exists():
        shutil.rmtree(DIST / "JileiScreenshot")
    # PyInstaller 必须用带依赖的解释器运行
    run([PYTHON, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=REPO)
    prune_qt_assets()
    thin_to_arm64()
    ensure_resources()
    sign_app()
    good = verify_app()
    if not good:
        print("!! 资源验证未全部通过，请检查上表 MISSING 项")
        sys.exit(1)
    print("\n构建完成: %s" % APP)


if __name__ == "__main__":
    main()
