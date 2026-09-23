#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jietuba macOS 打包脚本。

流程：
  1. 准备 .icns（从 托盘.ico / assets 生成，若缺失）
  2. PyInstaller onedir 构建 dist/Jietuba.app
  3. 补齐 models/（Contents/Resources + Contents/MacOS 双位置，兼容旧查找路径）
  4. ad-hoc 签名（无 Developer ID 时用 "-"；有则自动使用）
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
APP = DIST / "Jietuba.app"
SPEC = REPO / "jietuba_macos.spec"
ASSETS = REPO / "assets"
ICNS = ASSETS / "Jietuba.icns"
ENTITLEMENTS = REPO / "packaging" / "entitlements.plist"
VERSION = "2.0.6"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def ensure_icns():
    """从 托盘.ico 内嵌 PNG 生成 .icns（已存在则跳过）。"""
    if ICNS.exists():
        return
    ASSETS.mkdir(exist_ok=True)
    icon_png = REPO / "托盘.ico"
    tmp_png = "/tmp/jietuba_icon.png"
    iconset = "/tmp/jietuba.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset, exist_ok=True)

    code = f"""
from PIL import Image
import io
data = open(r"{icon_png}", "rb").read()
start = data.find(b"\\x89PNG")
img = Image.open(io.BytesIO(data[start:])).convert("RGBA")
img.save(r"{tmp_png}")
for s in (16, 32, 64, 128, 256, 512, 1024):
    im = img.resize((s, s), Image.LANCZOS)
    im.save(f"{iconset}/icon_{{s}}x{{s}}.png")
    if s >= 32:
        im.save(f"{iconset}/icon_{{s//2}}x{{s//2}}@2x.png")
"""
    run([VENV_PY, "-c", code])
    run(["iconutil", "-c", "icns", iconset, "-o", ICNS])
    print("icns ready:", ICNS)


def sign_app():
    """签名：优先 Developer ID Application，否则 ad-hoc（"-"）。"""
    identities = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    ).stdout
    ident = None
    for line in identities.splitlines():
        if "Developer ID Application" in line:
            ident = line.split('"')[1] if '"' in line else line.split()[1]
            break
    if ident is None:
        ident = "-"
        print("未找到 Developer ID Application，使用 ad-hoc 签名 (-)")
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
        print("（ad-hoc 签名：本地可运行；正式分发需 Developer ID + 公证）")
    else:
        print("spctl 通过")
    print("codesign done:", ident)


def ensure_resources():
    """OCR 模型双位置（Resources/models + MacOS/models），兼容 _MEIPASS 两种布局。"""
    for rel in ("Contents/Resources/models", "Contents/MacOS/models"):
        dst = APP / rel
        dst.mkdir(parents=True, exist_ok=True)
        for model in ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx"):
            src = REPO / "models" / model
            if src.exists() and not (dst / model).exists():
                shutil.copy2(src, dst / model)
    print("models copied")


def verify_app():
    ok = True
    checks = [
        ("executable", APP / "Contents/MacOS/Jietuba"),
        ("icon", APP / "Contents/Resources/Jietuba.icns"),
        ("det model", APP / "Contents/Resources/models/PP-OCRv6_det_small.onnx"),
        ("rec model", APP / "Contents/Resources/models/PP-OCRv6_rec_small.onnx"),
        ("svg", APP / "Contents/Resources/svg/托盘.svg"),
        ("qm", APP / "Contents/Resources/translations/app_zh.qm"),
    ]
    for name, p in checks:
        exists = p.exists()
        ok = ok and exists
        print(f"  [{'OK' if exists else 'MISSING'}] {name}: {p}")
    # Info.plist 关键键
    plist = APP / "Contents/Info.plist"
    if plist.exists():
        import plistlib
        with open(plist, "rb") as f:
            info = plistlib.load(f)
        for key in ("CFBundleIdentifier", "NSScreenCaptureUsageDescription",
                    "CFBundleShortVersionString"):
            print(f"  [{'OK' if key in info else 'MISSING'}] Info.plist {key} = {info.get(key)}")
        if info.get("CFBundleIdentifier") != "cc.jilei.jietuba":
            ok = False
    else:
        ok = False
    # Rust 扩展与关键 dylib
    for so in ("gifrecorder", "longstitch", "pyclipboard", "ppocr_rust"):
        found = list((APP / "Contents/Frameworks").rglob(f"{so}*.so"))
        found += list((APP / "Contents/Resources").rglob(f"{so}*.so"))
        print(f"  [{'OK' if found else 'MISSING'}] rust ext {so}: {found[0].name if found else ''}")
        ok = ok and bool(found)
    return ok


def main():
    ensure_icns()
    if APP.exists():
        shutil.rmtree(APP)
    if (DIST / "Jietuba").exists():
        shutil.rmtree(DIST / "Jietuba")
    # PyInstaller 必须用 venv python 运行（含依赖）
    run([VENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
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
