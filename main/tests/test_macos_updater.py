"""Mac 更新包安全边界：只使用临时目录，不联网、不替换真实应用。"""
import hashlib
import io
import plistlib
import sys
import tarfile
from types import SimpleNamespace

import pytest

from platforms.macos import updater

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app 更新契约")


def _archive(tmp_path, *, version="2.8.1", bundle_id=updater.BUNDLE_ID, extra=None):
    path = tmp_path / "test.app.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        files = {
            f"{updater.APP_NAME}/Contents/Info.plist": plistlib.dumps({
                "CFBundleIdentifier": bundle_id,
                "CFBundleShortVersionString": version,
                "CFBundleExecutable": "JileiScreenshot",
            }),
            f"{updater.APP_NAME}/Contents/MacOS/JileiScreenshot": b"test executable",
        }
        for name, contents in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(contents))
        if extra is not None:
            archive.addfile(extra)
    return path


def test_extract_accepts_matching_product_version(tmp_path):
    archive = _archive(tmp_path)
    app = updater._extract_app(archive, tmp_path / "out", "2.8.1")
    assert app.name == "积磊截图.app"
    assert (app / "Contents/MacOS/JileiScreenshot").is_file()


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "Other.app/Contents/file"])
def test_extract_rejects_paths_outside_product(tmp_path, name):
    archive = _archive(tmp_path, extra=tarfile.TarInfo(name))
    with pytest.raises(ValueError, match="非法路径"):
        updater._extract_app(archive, tmp_path / "out", "2.8.1")
    assert not (tmp_path / "out").exists()


def test_extract_rejects_escaping_symlink(tmp_path):
    member = tarfile.TarInfo(f"{updater.APP_NAME}/Contents/escape")
    member.type = tarfile.SYMTYPE
    member.linkname = "../../../../outside"
    archive = _archive(tmp_path, extra=member)
    with pytest.raises(tarfile.FilterError):
        updater._extract_app(archive, tmp_path / "out", "2.8.1")


@pytest.mark.parametrize("kwargs", [{"bundle_id": "other.product"}, {"version": "0.0.1"}])
def test_extract_rejects_product_or_version_mismatch(tmp_path, kwargs):
    archive = _archive(tmp_path, **kwargs)
    with pytest.raises(ValueError, match="产品或版本"):
        updater._extract_app(archive, tmp_path / "out", "2.8.1")


def test_signature_requires_existing_apple_team(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(stderr="TeamIdentifier=not set\n"))
    with pytest.raises(ValueError, match="未使用 Apple"):
        updater._verify_signature(tmp_path / "new.app", tmp_path / "old.app")


def test_signature_requires_same_team_and_bundle(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stderr="TeamIdentifier=TESTTEAM01\n")

    monkeypatch.setattr(updater.subprocess, "run", run)
    updater._verify_signature(tmp_path / "new.app", tmp_path / "old.app")
    requirement = calls[1][calls[1].index("-R") + 1]
    assert updater.BUNDLE_ID in requirement
    assert "TESTTEAM01" in requirement
    assert "anchor apple generic" in requirement
    assert calls[1][1:4] == ["--verify", "--deep", "--strict"]


@pytest.mark.parametrize("url,sha,size", [
    ("http://example.invalid/update", "a" * 64, 1),
    ("https://example.invalid/update", "missing", 1),
    ("https://example.invalid/update", "a" * 64, 0),
])
def test_download_rejects_invalid_manifest_before_network(monkeypatch, url, sha, size):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **kw:
                        pytest.fail("invalid manifest must not contact network"))
    info = SimpleNamespace(url=url, sha256=sha, size=size, version="2.8.1")
    assert updater.download_update(info) is None


def test_download_hash_mismatch_cleans_only_its_staging(monkeypatch, tmp_path):
    app = tmp_path / updater.APP_NAME
    app.mkdir()
    sentinel = tmp_path / "user-data.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(updater, "_current_app", lambda: app)

    class Response(io.BytesIO):
        def geturl(self):
            return "https://example.invalid/update"

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **kw: Response(b"bad"))
    info = SimpleNamespace(url="https://example.invalid/update", sha256="0" * 64,
                           size=3, version="2.8.1")
    assert updater.download_update(info) is None
    assert set(tmp_path.iterdir()) == {app, sentinel}
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_changed_download_cannot_start_installer(monkeypatch, tmp_path):
    archive = tmp_path / "update.app.tar.gz"
    archive.write_bytes(b"changed")
    monkeypatch.setattr(updater, "_downloads", {
        str(archive): ("2.8.1", hashlib.sha256(b"original").hexdigest()),
    })
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **kw:
                        pytest.fail("modified archive must not launch installer"))
    assert updater.install_and_restart(str(archive)) is False
    assert archive.read_bytes() == b"changed"
