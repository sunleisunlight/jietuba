"""macOS arm64 发布四件套，沿用同一产品、签名与只增不删归档约定。"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

import make_release_bundle as release


def make_dmg(app: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有 DMG: {output}")
    with tempfile.TemporaryDirectory(prefix="jilei_dmg_") as temp:
        source = Path(temp)
        # ditto preserves framework links, executable modes and signing resources.
        subprocess.run(["/usr/bin/ditto", str(app), str(source / app.name)], check=True)
        (source / "Applications").symlink_to("/Applications")
        subprocess.run(["hdiutil", "create", "-volname", "积磊截图", "-srcfolder", str(source),
                        "-format", "UDZO", str(output)], check=True)
    subprocess.run(["hdiutil", "verify", str(output)], check=True)


def make_macos_bundle(args) -> int:
    version = release.read_app_version()
    date = datetime.now().strftime("%y%m%d")
    stem = f"积磊截图-v{version}-{date}-macOS-arm64"
    names = (f"{stem}.app.tar.gz", f"{stem}.app.tar.gz.sig", f"{stem}.dmg",
             f"v{version}-{date}-macOS-更新说明.txt")
    raw = args.notes
    if args.notes_file:
        path = Path(args.notes_file)
        raw = (path if path.is_absolute() else release.REPO / path).read_text(encoding="utf-8")
    notes = release.collect_notes_lines(raw)
    if not notes:
        raise ValueError("请通过 --notes 或 --notes-file 提供更新说明")
    release.OUT.mkdir(parents=True, exist_ok=True)
    release.ensure_names_are_new(release.OUT, names)
    if args.build:
        subprocess.run([sys.executable, str(release.REPO / "build_macos.py")],
                       cwd=release.REPO, check=True)
    app = release.DIST / "积磊截图.app"
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleShortVersionString") != version or info.get("CFBundleIdentifier") != "cc.jilei.jileiscreenshot":
        raise ValueError("真实应用版本或 bundle ID 与当前发布不符")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    # lipo 的输入文件必须位于命令选项之前；错误顺序会把路径当成架构名。
    subprocess.run(["lipo", str(app / "Contents/MacOS/JileiScreenshot"), "-verify_arch", "arm64"], check=True)
    # staging 放 dist 下；失败时保留供定位/继续签名，绝不写出半套 release。
    staging = Path(tempfile.mkdtemp(prefix="macos-release-", dir=release.DIST))
    print(f"本轮暂存目录（未完成四件套不会进入 release）: {staging}", flush=True)
    artifact = staging / names[0]
    with tarfile.open(artifact, "w:gz", dereference=False) as archive:
        archive.add(app, arcname=app.name)
    make_dmg(app, staging / names[2])
    (staging / names[3]).write_text(
        release.build_notes_text(version, date, "darwin", "aarch64", notes), encoding="utf-8")
    release.sign_artifact(artifact)
    # 再检查一次，防构建期间同名发布被其它进程创建。使用硬链接保证不覆盖。
    release.ensure_names_are_new(release.OUT, names)
    for name in names:
        os.link(staging / name, release.OUT / name)
    hashes = "".join(f"{release.sha256_of(release.OUT / name)}  {name}\n" for name in names)
    (release.DIST / f"{stem}.sha256").write_text(hashes, encoding="utf-8")
    for name in names:
        print(release.OUT / name)
    print("四件套已完成；控制中心发布与人工验收仍由用户执行。")
    return 0
