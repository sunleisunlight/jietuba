"""macOS .app updater: verified archive, same signing identity, delayed replacement.

No sudo, no writes into user data, no overwriting previous release archives.
The old app remains in a unique sibling backup directory for recovery.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

_log = logging.getLogger(__name__)
BUNDLE_ID = "cc.jilei.jileiscreenshot"
APP_NAME = "积磊截图.app"
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_EXPANDED_BYTES = 6 * 1024**3
_downloads: dict[str, tuple[str, str]] = {}


def _current_app() -> Path:
    executable = Path(sys.executable).resolve()
    app = executable.parents[2]
    if not getattr(sys, "frozen", False) or app.suffix != ".app":
        raise RuntimeError("仅打包后的应用支持自动更新")
    if str(app).startswith("/Volumes/") or "AppTranslocation" in app.parts:
        raise RuntimeError("请先把应用从 DMG 拖到 Applications 后再更新")
    return app


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_update(info, progress=None, cancel_check=None):
    stage = None
    try:
        if not info.url.startswith("https://") or not re.fullmatch(r"[0-9a-fA-F]{64}", info.sha256):
            raise ValueError("更新清单缺少 HTTPS 地址或 SHA-256")
        if not 0 < info.size <= MAX_ARCHIVE_BYTES:
            raise ValueError("更新包大小无效")
        app = _current_app()
        # 与目标应用同一文件系统，后续 rename 可原子切换；权限不足直接失败。
        stage = Path(tempfile.mkdtemp(prefix=".jilei-update-", dir=app.parent))
        archive = stage / "update.app.tar.gz"
        request = urllib.request.Request(info.url, headers={"User-Agent": "JileiScreenshot-Updater"})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open("xb") as output:
            if not response.geturl().startswith("https://"):
                raise ValueError("拒绝非 HTTPS 重定向")
            done = 0
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError("取消下载")
                chunk = response.read(65536)
                if not chunk:
                    break
                done += len(chunk)
                if done > info.size:
                    raise ValueError("更新包超过清单大小")
                output.write(chunk)
                if progress:
                    progress(done, info.size)
        if done != info.size or _digest(archive) != info.sha256.lower():
            raise ValueError("更新包校验失败")
        _downloads[str(archive)] = (info.version, info.sha256.lower())
        return str(archive)
    except Exception:
        _log.exception("Mac 更新下载失败")
        if stage is not None:
            shutil.rmtree(stage)
        return None


def _extract_app(archive: Path, destination: Path, version: str) -> Path:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members or len(members) > 50000:
            raise ValueError("更新包文件数量无效")
        if sum(member.size for member in members) > MAX_EXPANDED_BYTES:
            raise ValueError("更新包解压大小超限")
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != APP_NAME:
                raise ValueError("更新包包含非法路径或其他产品")
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("更新包包含不支持的文件类型")
        # Python 3.11.16 data filter rejects escaping symlinks and device files.
        bundle.extractall(destination, filter="data")
    app = destination / APP_NAME
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleShortVersionString") != version:
        raise ValueError("更新包产品或版本与清单不符")
    executable = info.get("CFBundleExecutable", "")
    if not executable or Path(executable).name != executable:
        raise ValueError("更新包可执行文件无效")
    if not os.access(app / "Contents/MacOS" / executable, os.X_OK):
        raise ValueError("更新包缺少可执行程序")
    return app


def _verify_signature(new_app: Path, current_app: Path):
    details = subprocess.run(["/usr/bin/codesign", "-d", "--verbose=4", str(current_app)],
                             capture_output=True, text=True, check=True)
    team = re.search(r"^TeamIdentifier=([A-Z0-9]+)$", details.stderr, re.M)
    if not team or team.group(1) == "not":
        raise ValueError("当前应用未使用 Apple 证书签名，不能安全验证自动更新")
    requirement = f'identifier "{BUNDLE_ID}" and anchor apple generic and certificate leaf[subject.OU] = "{team.group(1)}"'
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "-R", requirement, str(new_app)],
                   check=True, capture_output=True)


# Positional arguments only: never interpolate paths into executable shell text.
# Wait for the old process to exit before replacing the bundle (single-instance lock).
_INSTALL_SCRIPT = r'''
pid=$1; current=$2; incoming=$3; backup=$4
count=0
while kill -0 "$pid" 2>/dev/null; do
    count=$((count + 1))
    [ "$count" -lt 120 ] || exit 1
    sleep 1
done
/bin/mv "$current" "$backup" || exit 2
if ! /bin/mv "$incoming" "$current"; then
    /bin/mv "$backup" "$current"
    exit 3
fi
/usr/bin/open "$current"
'''


def install_and_restart(archive_path: str) -> bool:
    try:
        version, expected_hash = _downloads[archive_path]
        archive = Path(archive_path)
        if _digest(archive) != expected_hash:
            raise ValueError("下载后的更新包发生变化")
        current = _current_app()
        if archive.parent.parent != current.parent:
            raise ValueError("更新目录不是目标应用的同级暂存目录")
        unpack = archive.parent / "unpacked"
        unpack.mkdir()
        incoming = _extract_app(archive, unpack, version)
        _verify_signature(incoming, current)
        backup = archive.parent / current.name
        with (archive.parent / "install.log").open("ab") as log:
            subprocess.Popen(["/bin/sh", "-c", _INSTALL_SCRIPT, "jilei-updater",
                              str(os.getpid()), str(current), str(incoming), str(backup)],
                             cwd="/", stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, close_fds=True)
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
        return True
    except Exception:
        _log.exception("Mac 更新安装失败；原应用与下载包保留")
        return False
