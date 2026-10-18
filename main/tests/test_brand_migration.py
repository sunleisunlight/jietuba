# -*- coding: utf-8 -*-
"""品牌升级迁移（截图吧/jietuba → 积磊截图/JileiScreenshot）测试。"""
import os
import sys

import pytest

from core.brand_migration import (
    LEGACY_THEME_COLOR,
    NEW_THEME_COLOR,
    copy_qsettings,
    migrate_app_data_dir,
    migrate_legacy_defaults,
    migrate_windows_autostart,
    migrate_windows_desktop_shortcut,
)


# ── 应用数据目录 ────────────────────────────────────────────

def test_app_data_dir_rename_whole_dir(tmp_path):
    old = tmp_path / "Jietuba"
    new = tmp_path / "JileiScreenshot"
    (old / "Logs").mkdir(parents=True)
    (old / "Logs" / "run.log").write_text("log", encoding="utf-8")

    assert migrate_app_data_dir(old, new) is True

    assert not old.exists()
    assert (new / "Logs" / "run.log").read_text(encoding="utf-8") == "log"


def test_app_data_dir_merge_keeps_new_files(tmp_path):
    old = tmp_path / "Jietuba"
    new = tmp_path / "JileiScreenshot"
    old.mkdir()
    new.mkdir()
    (old / "only_old.txt").write_text("old", encoding="utf-8")
    (new / "keep.txt").write_text("new", encoding="utf-8")

    migrate_app_data_dir(old, new)

    assert (new / "only_old.txt").read_text(encoding="utf-8") == "old"
    # 同名（新目录已有）文件绝不被老数据覆盖
    assert (new / "keep.txt").read_text(encoding="utf-8") == "new"


def test_app_data_dir_nothing_to_do(tmp_path):
    old = tmp_path / "Jietuba"
    new = tmp_path / "JileiScreenshot"
    new.mkdir()
    assert migrate_app_data_dir(old, new) is False


def test_app_data_dir_falls_back_to_merge_when_rename_locked(tmp_path, monkeypatch):
    """旧版本仍在运行、整目录被锁住（rename 抛 OSError）时，降级逐项合并。"""
    import os as _os

    old = tmp_path / "Jietuba"
    new = tmp_path / "JileiScreenshot"
    (old / "History").mkdir(parents=True)
    (old / "History" / "shot.png").write_bytes(b"\x89PNG")

    real_rename = _os.rename

    def _rename(src, dst):
        # 仅整目录重命名被"锁住"，子项移动正常
        if _os.path.abspath(str(src)) == _os.path.abspath(str(old)):
            raise OSError("another running app holds the directory")
        return real_rename(src, dst)

    monkeypatch.setattr("core.brand_migration.os.rename", _rename)

    assert migrate_app_data_dir(old, new) is True
    assert (new / "History" / "shot.png").read_bytes() == b"\x89PNG"
    # History 已搬走，只剩空壳旧目录（被锁时保留也无害）
    assert not (old / "History").exists()


def test_move_tree_recurses_when_nested_dir_locked(tmp_path, monkeypatch):
    """顶层和中间层目录都被锁时，文件仍能逐层搬到目标树。"""
    import os as _os
    from core.brand_migration import _move_tree

    src = tmp_path / "History"
    project = src / "projA"
    project.mkdir(parents=True)
    (project / "shot.png").write_bytes(b"img")

    real_rename = _os.rename

    def _rename(s, d):
        # 任何"目录"级重命名都被锁，只允许文件移动
        if _os.path.isdir(s):
            raise PermissionError(1, "locked", str(s))
        return real_rename(s, d)

    monkeypatch.setattr("core.brand_migration.os.rename", _rename)

    dst = tmp_path / "History_new"
    assert _move_tree(src, dst) is True
    assert (dst / "projA" / "shot.png").read_bytes() == b"img"
    # 空壳目录被清掉
    assert not (project).exists()


# ── QSettings ───────────────────────────────────────────────

def _ini(tmp_path, name):
    from PySide6.QtCore import QSettings
    return QSettings(str(tmp_path / name), QSettings.Format.IniFormat)


def test_copy_qsettings_with_nested_groups(qapp, tmp_path):
    src = _ini(tmp_path, "old.ini")
    dst = _ini(tmp_path, "new.ini")
    src.setValue("app/theme_color", LEGACY_THEME_COLOR)
    src.beginGroup("inapp")
    src.setValue("screenshot", "A")
    src.endGroup()
    src.sync()

    assert copy_qsettings(src, dst) == 2

    dst2 = _ini(tmp_path, "new.ini")
    assert dst2.value("app/theme_color") == LEGACY_THEME_COLOR
    assert dst2.value("inapp/screenshot") == "A"


def test_copy_qsettings_skips_nonempty_dst(qapp, tmp_path):
    src = _ini(tmp_path, "old.ini")
    dst = _ini(tmp_path, "new.ini")
    src.setValue("app/theme_color", "#FF0000")
    dst.setValue("app/keep", "1")
    src.sync()
    dst.sync()

    assert copy_qsettings(src, dst) == 0

    dst2 = _ini(tmp_path, "new.ini")
    assert dst2.value("app/theme_color") is None
    assert dst2.value("app/keep") == "1"


def test_copy_qsettings_empty_src(qapp, tmp_path):
    assert copy_qsettings(_ini(tmp_path, "a.ini"), _ini(tmp_path, "b.ini")) == 0


# ── 旧默认值迁移 ────────────────────────────────────────────

def test_legacy_theme_color_migrates_to_brand_orange(qapp, tmp_path):
    s = _ini(tmp_path, "s.ini")
    s.setValue("app/theme_color", LEGACY_THEME_COLOR)
    s.sync()

    migrate_legacy_defaults(s)

    assert s.value("app/theme_color") == NEW_THEME_COLOR


def test_custom_theme_color_is_preserved(qapp, tmp_path):
    s = _ini(tmp_path, "s.ini")
    s.setValue("app/theme_color", "#123456")
    s.sync()

    migrate_legacy_defaults(s)

    assert s.value("app/theme_color") == "#123456"


def test_missing_theme_color_left_untouched(qapp, tmp_path):
    s = _ini(tmp_path, "s.ini")
    migrate_legacy_defaults(s)
    assert s.value("app/theme_color") is None


def test_legacy_save_path_rewritten_when_dir_absent(qapp, tmp_path, monkeypatch):
    # 把"图片库"指到临时目录，避免碰开发机真实 Pictures
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake_home)))

    s = _ini(tmp_path, "s.ini")
    old_photos = fake_home / "Pictures" / "jietuba_photos"
    s.setValue("app/screenshot_save_path", str(old_photos))
    s.sync()

    migrate_legacy_defaults(s)

    expected = os.path.join(str(fake_home), "Pictures", "JileiScreenshot_photos")
    assert os.path.normpath(s.value("app/screenshot_save_path")) == os.path.normpath(expected)


def test_custom_save_path_is_preserved(qapp, tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake_home)))

    s = _ini(tmp_path, "s.ini")
    custom = str(tmp_path / "my_shots")
    s.setValue("app/screenshot_save_path", custom)
    s.sync()

    migrate_legacy_defaults(s)

    assert s.value("app/screenshot_save_path") == custom


def test_legacy_save_dir_physically_renamed(qapp, tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake_home)))

    old_photos = fake_home / "Pictures" / "jietuba_photos"
    old_photos.mkdir(parents=True)
    (old_photos / "shot.png").write_bytes(b"\x89PNG")

    s = _ini(tmp_path, "s.ini")
    s.setValue("app/screenshot_save_path", str(old_photos))
    s.sync()

    migrate_legacy_defaults(s)

    new_photos = fake_home / "Pictures" / "JileiScreenshot_photos"
    assert not old_photos.exists()
    assert (new_photos / "shot.png").read_bytes() == b"\x89PNG"
    assert os.path.normpath(s.value("app/screenshot_save_path")) == os.path.normpath(str(new_photos))


def test_legacy_save_dir_takes_over_empty_new_dir(qapp, tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake_home)))

    pictures = fake_home / "Pictures"
    old_photos = pictures / "jietuba_photos"
    new_photos = pictures / "JileiScreenshot_photos"
    old_photos.mkdir(parents=True)
    (old_photos / "shot.png").write_bytes(b"\x89PNG")
    new_photos.mkdir()  # 新版本预建的空目录

    s = _ini(tmp_path, "s.ini")
    s.setValue("app/screenshot_save_path", str(old_photos))
    s.sync()

    migrate_legacy_defaults(s)

    assert not old_photos.exists()
    assert (new_photos / "shot.png").read_bytes() == b"\x89PNG"
    assert os.path.normpath(s.value("app/screenshot_save_path")) == os.path.normpath(str(new_photos))


# ── Windows 系统集成项（仅 Windows 运行）────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="Windows 注册表专属测试")
class TestWindowsIntegration:
    def test_autostart_migrated_in_isolated_regkey(self, tmp_path):
        import winreg

        # 用 HKCU 下的临时子键做沙盒，绝碰真实 Run 键
        sandbox = r"SOFTWARE\JileiScreenshotTests\Run"
        fake_old_exe = tmp_path / "jietuba_pp.exe"
        fake_old_exe.write_bytes(b"")
        # migrate 函数固定在旧目标旁寻找新 exe
        fake_new_exe = tmp_path / "积磊截图.exe"
        fake_new_exe.write_bytes(b"")

        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, sandbox)
            winreg.SetValueEx(key, "Jietuba", 0, winreg.REG_SZ, f'"{fake_old_exe}"')
            winreg.CloseKey(key)

            assert migrate_windows_autostart(
                run_key=sandbox, legacy_name="Jietuba", new_name="JileiScreenshot",
                frozen=True,
            ) is True

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sandbox)
            value, _ = winreg.QueryValueEx(key, "JileiScreenshot")
            with pytest.raises(FileNotFoundError):
                winreg.QueryValueEx(key, "Jietuba")
            winreg.CloseKey(key)
            assert str(fake_new_exe) in value
        finally:
            self._delete_regkey_tree(sandbox)

    def test_autostart_kept_when_new_exe_missing(self, tmp_path):
        import winreg

        sandbox = r"SOFTWARE\JileiScreenshotTests\RunMissing"
        fake_old_exe = tmp_path / "jietuba_pp.exe"
        fake_old_exe.write_bytes(b"")
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, sandbox)
            winreg.SetValueEx(key, "Jietuba", 0, winreg.REG_SZ, f'"{fake_old_exe}"')
            winreg.CloseKey(key)

            assert migrate_windows_autostart(
                run_key=sandbox, legacy_name="Jietuba", new_name="JileiScreenshot",
                frozen=True,
            ) is False

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sandbox)
            # 旧项原样保留，不产生指向空路径的新项
            assert winreg.QueryValueEx(key, "Jietuba")[0] == f'"{fake_old_exe}"'
            with pytest.raises(FileNotFoundError):
                winreg.QueryValueEx(key, "JileiScreenshot")
            winreg.CloseKey(key)
        finally:
            self._delete_regkey_tree(sandbox)

    def test_desktop_shortcut_migrated(self, qapp, tmp_path, monkeypatch):
        # Migration is deliberately non-fatal at startup. Surface its diagnostic
        # on CI instead of reducing a native PowerShell/COM failure to False.
        messages = []
        monkeypatch.setattr("core.brand_migration._log",
                            lambda level, message: messages.append((level, message)))
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        (desktop / "Jietuba.lnk").write_bytes(b"")
        exe = tmp_path / "积磊截图.exe"
        exe.write_bytes(b"")

        assert migrate_windows_desktop_shortcut(
            desktop_dir=str(desktop), exe_path=str(exe),
        ) is True, messages

        assert (desktop / "积磊截图.lnk").exists()
        assert not (desktop / "Jietuba.lnk").exists()

    @staticmethod
    def _delete_regkey_tree(subkey: str) -> None:
        import winreg

        def _delete(root, path):
            try:
                key = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
            except FileNotFoundError:
                return
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                winreg.CloseKey(key)
                _delete(root, f"{path}\\{child}")
                key = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
            winreg.CloseKey(key)
            winreg.DeleteKey(root, path)

        _delete(winreg.HKEY_CURRENT_USER, subkey)
