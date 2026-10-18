# -*- coding: utf-8 -*-
"""品牌升级一次性迁移：截图吧/jietuba → 积磊截图/JileiScreenshot。

必须在 QApplication 与任何业务窗口创建之前执行（bootstrap.run 早期调用），
把老版本留在本机的数据与系统集成项搬到新品牌名下：

1. 应用数据目录 Jietuba → JileiScreenshot（日志、崩溃记录等）；
2. 三组 QSettings 老配置复制到新组织/应用名（含嵌套分组）；
3. 老默认截图主题色（青绿 #40E0D0）迁到品牌橙，用户自定义色不动；
4. 老默认截图保存目录跟随改名，并尝试物理迁移目录；
5. Windows 开机自启注册表项、桌面快捷方式改指向新 exe；
6. macOS LaunchAgent plist 的 label 与 .app 路径跟随改名。

所有步骤都幂等：新位置已有数据时不覆盖；任何一步失败只写日志/警告，
绝不阻断应用启动——迁移是锦上添花，不能变成新版本的启动风险。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── 迁移契约常量 ────────────────────────────────────────────

# （旧组织名, 旧应用名, 新组织名, 新应用名）
QSETTINGS_MIGRATIONS = (
    ("Jietuba", "ToolSettings", "JileiScreenshot", "ToolSettings"),
    ("Jietuba", "ClipboardWindow", "JileiScreenshot", "ClipboardWindow"),
    ("Fandes", "jietuba", "JileiScreenshot", "LongStitch"),
)

# 老默认截图主题色 → 品牌橙（仅迁移"从未自定义"的用户）
LEGACY_THEME_COLOR = "#40E0D0"
NEW_THEME_COLOR = "#FF5A1F"

LEGACY_PHOTOS_DIRNAME = "jietuba_photos"
NEW_PHOTOS_DIRNAME = "JileiScreenshot_photos"

# Windows 开机自启 / 桌面快捷方式
_RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
LEGACY_AUTOSTART_VALUE = "Jietuba"
NEW_AUTOSTART_VALUE = "JileiScreenshot"
NEW_EXE_NAME = "积磊截图.exe"
LEGACY_SHORTCUT_NAME = "Jietuba.lnk"
NEW_SHORTCUT_NAME = "积磊截图.lnk"

# macOS LaunchAgent
LEGACY_LAUNCH_AGENT_LABEL = "cc.jilei.jietuba"
NEW_LAUNCH_AGENT_LABEL = "cc.jilei.jileiscreenshot"
LEGACY_APP_BUNDLE = "Jietuba.app"
NEW_APP_BUNDLE = "积磊截图.app"


def _log(level: str, message: str) -> None:
    """迁移在日志系统初始化之前运行，尽量走 logger；失败则静默降级。"""
    try:
        from core.logger import log_info, log_warning
        if level == "info":
            log_info(message, "BrandMigration")
        else:
            log_warning(message, "BrandMigration")
    except Exception:
        pass


# ── 1. 应用数据目录 ─────────────────────────────────────────

def _move_tree(src: Path, dst: Path) -> bool:
    """把一个文件系统项搬到 dst；目录本身被锁时降级为逐孩子搬迁。

    Windows 上运行中的旧版本可能持有目录级句柄（日志文件、目录监听等），
    此时整目录 os.rename 会抛 PermissionError，但目录内未被打开的子项
    依旧可以移动——先建目标目录，再把孩子逐个搬过去，最后尝试删掉空壳，
    删不掉也无妨（下次启动幂等重试）。
    """
    try:
        os.rename(src, dst)
        return True
    except OSError:
        if not src.is_dir():
            return False

    moved_something = False
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            target = dst / child.name
            if target.exists():
                continue
            try:
                if _move_tree(child, target):
                    moved_something = True
            except OSError:
                continue
        try:
            src.rmdir()
        except OSError:
            pass
    except OSError:
        return moved_something
    return moved_something


def migrate_app_data_dir(old_dir: Path | None = None,
                         new_dir: Path | None = None) -> bool:
    """把旧数据目录整体迁到新目录名。

    - 新目录不存在：直接整体重命名（同盘原子操作，最快最完整）；
    - 新目录已存在（少见，例如用户手动建过）：逐文件合并，新目录已有的
      文件不覆盖，保证新版本数据优先；
    - 旧目录不存在：无事可做。

    返回是否发生了迁移。
    """
    if old_dir is None or new_dir is None:
        from core.constants import get_app_data_dir, get_legacy_app_data_dir
        old_dir = get_legacy_app_data_dir()
        new_dir = get_app_data_dir()

    if not old_dir.exists() or not old_dir.is_dir():
        return False

    try:
        if not new_dir.exists():
            try:
                # 最干净的路径：整目录同盘原子重命名
                os.rename(old_dir, new_dir)
                _log("info", f"应用数据目录已重命名: {old_dir} -> {new_dir}")
                return True
            except OSError:
                # 典型场景：旧版本仍在运行、持有日志/数据库文件句柄，
                # Windows 不允许重命名内含打开句柄的目录。降级为逐项合并，
                # 被锁住的项跳过，下次启动继续（本函数幂等）。
                pass

        new_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for item in old_dir.iterdir():
            target = new_dir / item.name
            if target.exists():
                continue  # 新目录已有同名项，保留新的
            try:
                if _move_tree(item, target):
                    moved += 1
            except OSError:
                pass
        # 旧目录能清空就删掉，否则留着也无害（下次启动再合）
        try:
            old_dir.rmdir()
        except OSError:
            pass
        _log("info", f"应用数据目录已合并到 {new_dir}（迁移 {moved} 项）")
        return moved > 0
    except Exception as e:
        _log("warning", f"应用数据目录迁移失败，保留旧目录 {old_dir}: {e}")
        return False


# ── 2. QSettings ────────────────────────────────────────────

def copy_qsettings(src, dst) -> int:
    """把一个 QSettings 的全部键值（含嵌套分组）复制到另一个。

    目标已有任何内容时跳过，保证不覆盖新版本自己写下的数据。
    纯函数式、不关心后端格式（注册表/plist/INI 都走同一套 API），
    因此测试里可以直接喂 IniFormat 的临时实例。返回复制的键数量。
    """
    if not src.childKeys() and not src.childGroups():
        return 0
    if dst.childKeys() or dst.childGroups():
        return 0

    copied = 0

    def _walk(group: str = "") -> None:
        nonlocal copied
        if group:
            src.beginGroup(group)
            dst.beginGroup(group)
        for key in src.childKeys():
            dst.setValue(key, src.value(key))
            copied += 1
        for child in src.childGroups():
            _walk(child)
        if group:
            dst.endGroup()
            src.endGroup()

    _walk()
    dst.sync()
    return copied


def migrate_all_qsettings(factory=None) -> int:
    """迁移全部老 QSettings 存储。factory 用于测试注入（默认真机构造）。"""
    from PySide6.QtCore import QSettings

    def _factory(org: str, app: str):
        return QSettings(org, app)

    factory = factory or _factory
    total = 0
    for old_org, old_app, new_org, new_app in QSETTINGS_MIGRATIONS:
        try:
            n = copy_qsettings(factory(old_org, old_app),
                               factory(new_org, new_app))
            if n:
                total += n
                _log("info", f"配置已迁移 {old_org}/{old_app} -> {new_org}/{new_app}（{n} 项）")
        except Exception as e:
            _log("warning", f"配置迁移失败 {old_org}/{old_app}: {e}")
    return total


# ── 3-4. 默认色 / 默认保存目录（在新 ToolSettings 上做）────

def migrate_legacy_defaults(settings) -> None:
    """老用户配置里残留的"旧默认值"升级为新品牌默认值。

    - theme_color 恰好是旧青绿 → 品牌橙；自定义过的任何颜色都不动；
    - screenshot_save_path 恰好是旧默认图片目录 → 新默认目录，并尝试
      把旧图片文件夹整体改名（占用/权限失败时只改配置指向，文件保留）。
    """
    try:
        saved_color = settings.value("app/theme_color")
        if isinstance(saved_color, str) and saved_color.strip().lower() == LEGACY_THEME_COLOR.lower():
            settings.setValue("app/theme_color", NEW_THEME_COLOR)
            settings.sync()
            _log("info", f"旧默认截图主题色 {LEGACY_THEME_COLOR} 已迁移为品牌橙 {NEW_THEME_COLOR}")
    except Exception as e:
        _log("warning", f"主题色迁移失败: {e}")

    try:
        saved_path = settings.value("app/screenshot_save_path")
        if isinstance(saved_path, str) and saved_path.strip():
            old_photos = os.path.normcase(os.path.normpath(
                os.path.join(os.path.expanduser("~"), "Pictures", LEGACY_PHOTOS_DIRNAME)))
            if os.path.normcase(os.path.normpath(saved_path)) == old_photos:
                new_photos = os.path.join(
                    os.path.expanduser("~"), "Pictures", NEW_PHOTOS_DIRNAME)

                def _is_empty_dir(path: str) -> bool:
                    try:
                        return os.path.isdir(path) and not os.listdir(path)
                    except OSError:
                        return False

                if os.path.isdir(old_photos):
                    # 新版本已预建了一个空的新目录时，先删空壳再接管，
                    # 保证 118 张老截图整体搬过去而不是留在旧名下。
                    if _is_empty_dir(new_photos):
                        try:
                            os.rmdir(new_photos)
                        except OSError:
                            pass
                    try:
                        _move_tree(Path(old_photos), Path(new_photos))
                        _log("info", f"截图保存目录已迁移: {old_photos} -> {new_photos}")
                    except OSError as e:
                        # 目录被占用或在 OneDrive 等重定向下移动失败：保留文件位置，
                        # 让新配置继续指向老目录，绝不丢用户图片。
                        _log("warning", f"截图保存目录移动失败，保留原路径: {e}")
                        return
                if not os.path.isdir(old_photos):
                    settings.setValue("app/screenshot_save_path", new_photos)
                    settings.sync()
    except Exception as e:
        _log("warning", f"截图保存目录迁移失败: {e}")


# ── 5. Windows 自启项与桌面快捷方式 ─────────────────────────

def _new_exe_alongside(old_target: str) -> str | None:
    """旧自启目标同目录下的新品牌 exe 路径；不存在返回 None。"""
    target = old_target.strip().strip('"')
    candidate = os.path.join(os.path.dirname(target), NEW_EXE_NAME)
    return candidate if os.path.isfile(candidate) else None


def migrate_windows_autostart(run_key: str = _RUN_KEY,
                              legacy_name: str = LEGACY_AUTOSTART_VALUE,
                              new_name: str = NEW_AUTOSTART_VALUE,
                              frozen: bool | None = None) -> bool:
    """把 HKCU\\Run 里旧品牌自启项改名并指向新 exe。仅打包态有意义。"""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if sys.platform != "win32" or not frozen:
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, run_key, 0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        )
    except OSError:
        return False

    try:
        try:
            legacy_value, _ = winreg.QueryValueEx(key, legacy_name)
        except FileNotFoundError:
            return False
        new_exe = _new_exe_alongside(str(legacy_value))
        if not new_exe:
            # 新 exe 不在旧 exe 旁边（可能是绿色版换了目录）：保留旧项，
            # 不做可能指向空路径的改写。
            return False
        try:
            winreg.DeleteValue(key, legacy_name)
        except FileNotFoundError:
            pass
        winreg.SetValueEx(key, new_name, 0, winreg.REG_SZ, f'"{new_exe}"')
        _log("info", f"开机自启项已迁移: {legacy_name} -> {new_name} ({new_exe})")
        return True
    except Exception as e:
        _log("warning", f"开机自启项迁移失败: {e}")
        return False
    finally:
        winreg.CloseKey(key)


def migrate_windows_desktop_shortcut(desktop_dir: str | None = None,
                                     exe_path: str | None = None,
                                     legacy_lnk: str = LEGACY_SHORTCUT_NAME,
                                     new_lnk: str = NEW_SHORTCUT_NAME) -> bool:
    """把桌面上的旧品牌快捷方式改名并指向新 exe（WScript.Shell COM）。"""
    if sys.platform != "win32":
        return False

    if desktop_dir is None:
        # 仅在打包态动真实桌面；开发态必须显式传参（测试用）
        if not getattr(sys, "frozen", False):
            return False
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    if exe_path is None:
        exe_path = sys.executable

    old_lnk_path = os.path.join(desktop_dir, legacy_lnk)
    new_lnk_path = os.path.join(desktop_dir, new_lnk)
    if not os.path.isfile(old_lnk_path):
        return False
    if not os.path.isfile(exe_path):
        return False
    try:
        # 与欢迎向导（page6_finish）保持同一套 PowerShell WScript.Shell 方案：
        # onefile 打包不收集 win32com，COM 直调在生产环境会 ImportError。
        import base64
        import subprocess

        working_dir = os.path.dirname(exe_path)

        def _ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        script = "\n".join([
            f"$shortcutPath = {_ps_quote(new_lnk_path)}",
            f"$targetPath = {_ps_quote(exe_path)}",
            f"$workingDirectory = {_ps_quote(working_dir)}",
            "$shell = New-Object -ComObject WScript.Shell",
            "$shortcut = $shell.CreateShortcut($shortcutPath)",
            "$shortcut.TargetPath = $targetPath",
            "$shortcut.WorkingDirectory = $workingDirectory",
            "$shortcut.IconLocation = $targetPath",
            "$shortcut.Save()",
        ])
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded,
            ],
            capture_output=True, text=True, timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not os.path.isfile(new_lnk_path):
            raise RuntimeError((result.stderr or result.stdout or "powershell failed").strip())
        try:
            os.remove(old_lnk_path)
        except OSError:
            pass
        _log("info", f"桌面快捷方式已迁移: {legacy_lnk} -> {new_lnk}")
        return True
    except Exception as e:
        _log("warning", f"桌面快捷方式迁移失败: {e}")
        return False


# ── 6. macOS LaunchAgent ────────────────────────────────────

def migrate_macos_launch_agent(agents_dir: str | None = None) -> bool:
    """旧 label 的 LaunchAgent plist 改名并替换内部 Label/.app 路径。"""
    if sys.platform != "darwin":
        return False
    agents_dir = agents_dir or os.path.join(
        os.path.expanduser("~"), "Library", "LaunchAgents")
    old_plist = os.path.join(agents_dir, f"{LEGACY_LAUNCH_AGENT_LABEL}.plist")
    new_plist = os.path.join(agents_dir, f"{NEW_LAUNCH_AGENT_LABEL}.plist")
    if not os.path.isfile(old_plist) or os.path.exists(new_plist):
        return False
    try:
        with open(old_plist, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(LEGACY_LAUNCH_AGENT_LABEL, NEW_LAUNCH_AGENT_LABEL)
        content = content.replace(LEGACY_APP_BUNDLE, NEW_APP_BUNDLE)
        with open(new_plist, "w", encoding="utf-8") as f:
            f.write(content)
        os.remove(old_plist)
        _log("info", f"LaunchAgent 已迁移: {old_plist} -> {new_plist}")
        return True
    except Exception as e:
        _log("warning", f"LaunchAgent 迁移失败: {e}")
        return False


# ── 总入口 ──────────────────────────────────────────────────

def run_brand_migration() -> None:
    """启动早期一次性执行全部品牌迁移。任何异常都不外抛。"""
    try:
        migrate_app_data_dir()
        migrate_all_qsettings()

        # 默认色/保存目录的迁移对象是复制完成后的新 ToolSettings
        try:
            from PySide6.QtCore import QSettings
            migrate_legacy_defaults(QSettings("JileiScreenshot", "ToolSettings"))
        except Exception as e:
            _log("warning", f"默认值迁移跳过: {e}")

        if sys.platform == "win32":
            migrate_windows_autostart()
            migrate_windows_desktop_shortcut()
        elif sys.platform == "darwin":
            migrate_macos_launch_agent()
    except Exception as e:
        _log("warning", f"品牌迁移整体异常（不影响启动）: {e}")
