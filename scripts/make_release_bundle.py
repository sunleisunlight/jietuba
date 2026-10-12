# -*- coding: utf-8 -*-
"""积磊截图 Windows 发布四件套一键打包。

产出到 dist/release/（平铺）：
  ① 积磊截图-v<版本>-<YYMMDD>-Windows-x64.exe
  ② models.zip
  ③ v<版本>-<YYMMDD>-更新说明.txt
  ④ 积磊截图-v<版本>-<YYMMDD>-Windows-x64.sha256

用法：
  python scripts/make_release_bundle.py                # 用现有 dist/积磊截图.exe
  python scripts/make_release_bundle.py --build        # 先跑 build_with_ocr_onefile.py
  python scripts/make_release_bundle.py --notes "本次改动说明"
版本号始终从 main/main_app.py 的 APP_VERSION 静态解析（不 import，避免 PySide 副作用）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
OUT = DIST / "release"
EXE_NAME = "积磊截图.exe"
MODELS = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx")


def read_app_version() -> str:
    tree = ast.parse((REPO / "main" / "main_app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets)
                and isinstance(node.value, ast.Constant)):
            return str(node.value.value)
    raise RuntimeError("无法从 main/main_app.py 解析 APP_VERSION")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="打包前先运行 build_with_ocr_onefile.py")
    ap.add_argument("--notes", default="", help="本次更新说明（不传则生成模板）")
    ap.add_argument("--arch", default="x64", choices=["x64", "arm64"])
    args = ap.parse_args()

    version = read_app_version()
    date = datetime.now().strftime("%y%m%d")
    stem = f"积磊截图-v{version}-{date}-Windows-{args.arch}"

    if args.build:
        print("==> 构建 onefile exe …")
        r = subprocess.run([sys.executable, str(REPO / "build_with_ocr_onefile.py")], cwd=REPO)
        if r.returncode != 0:
            print("!! 构建失败")
            return r.returncode

    exe = DIST / EXE_NAME
    if not exe.exists():
        print(f"!! 找不到 {exe}，请先加 --build 或运行 build_with_ocr_onefile.py")
        return 1

    models_dir = DIST / "models"
    missing = [m for m in MODELS if not (models_dir / m).exists()]
    if missing:
        print(f"!! 缺少 OCR 模型: {missing}（应在 {models_dir}）")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    # 清理同名旧产物，避免混入
    for p in OUT.glob("*"):
        if p.is_file():
            p.unlink()

    # ① exe
    bundle_exe = OUT / f"{stem}.exe"
    shutil.copy2(exe, bundle_exe)

    # ② models.zip
    models_zip = OUT / "models.zip"
    with zipfile.ZipFile(models_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for m in MODELS:
            z.write(models_dir / m, arcname=f"models/{m}")

    # ③ 更新说明
    notes = args.notes.strip() or (
        f"积磊截图 v{version}\n"
        f"\n"
        f"发布日期：{datetime.now().strftime('%Y-%m-%d')}\n"
        f"\n"
        f"更新内容：\n"
        f"- （发布前在此补充本次变化）\n"
    )
    notes_txt = OUT / f"v{version}-{date}-更新说明.txt"
    notes_txt.write_text(notes, encoding="utf-8")

    # ④ sha256
    digest = sha256_of(bundle_exe)
    sha_file = OUT / f"{stem}.sha256"
    sha_file.write_text(f"{digest}  {bundle_exe.name}\n", encoding="utf-8")

    print("=" * 60)
    print("四件套已生成：", OUT)
    for p in (bundle_exe, models_zip, notes_txt, sha_file):
        size = p.stat().st_size
        print(f"  {p.name}  ({size:,} bytes)")
    print(f"SHA-256: {digest}")
    print("=" * 60)
    print("下一步：把这四个文件上传到积磊控制中心后台「发布中心」发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
