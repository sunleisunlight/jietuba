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

    双位置拷贝（Contents/Resources + Contents/MacOS）：应用运行时按
    ``sys.executable`` 同级的 ``models/`` 查找（即 Contents/MacOS/models），
    Resources/models 作为惯例位置一并保留。
    """
    src_dir = REPO / "models"
    missing = [name for name in MODELS if not (src_dir / name).is_file()]
    if missing:
        print("!! 缺少 OCR 模型: %s" % ", ".join(missing))
        print("   仓库 models/ 必须包含: %s" % ", ".join(MODELS))
        print("   Mac 正式构建要求 OCR 与 Windows 对齐，模型不是可选项。")
        sys.exit(1)
    for rel in ("Contents/Resources/models", "Contents/MacOS/models"):
        dst = APP / rel
        dst.mkdir(parents=True, exist_ok=True)
        for name in MODELS:
            shutil.copy2(src_dir / name, dst / name)
    print("models copied:", ", ".join(MODELS))


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
        ("det model (MacOS)", APP / "Contents/MacOS/models/PP-OCRv6_det_small.onnx"),
        ("rec model (MacOS)", APP / "Contents/MacOS/models/PP-OCRv6_rec_small.onnx"),
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
    ensure_resources()
    sign_app()
    good = verify_app()
    if not good:
        print("!! 资源验证未全部通过，请检查上表 MISSING 项")
        sys.exit(1)
    print("\n构建完成: %s" % APP)


if __name__ == "__main__":
    main()
