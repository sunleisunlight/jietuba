# -*- coding: utf-8 -*-
"""积磊截图自动更新器（Python onefile 版）。

与积磊控制中心的 Tauri 更新清单同一套接口合同：
    GET /updates/jilei-screenshot/stable/<target>/<arch>/<current_version>
- 无更新：HTTP 204
- 有更新：JSON {version, notes, pub_date, url, sha256, size, displayVersion}

安全：强制 HTTPS；下载后用服务端清单里的 SHA-256 做完整性校验（清单本身经
HTTPS 传输，SHA-256 防下载损坏/被篡改）。Windows 下 onefile exe 运行时被锁定，
采用「先把运行中的 exe 改名 → 新 exe 就位 → 启动新版 → 退出本进程」的进程内替换法
（Windows 允许重命名运行中的 exe，但不允许覆盖/删除），旧文件下次启动清理。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from core.logger import log_info, log_warning, T
from main_app import APP_VERSION

PRODUCT_ID = "jilei-screenshot"
CHANNEL = "stable"
BASE_URLS = ("https://cc.jilei.cc", "https://cc.sunget.top")


@dataclass
class UpdateInfo:
    version: str
    notes: str
    url: str
    sha256: str
    size: int
    pub_date: str = ""


def _target_arch() -> tuple[str, str]:
    if sys.platform == "darwin":
        return "darwin", "universal"
    import platform
    machine = (platform.machine() or "").lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    return "windows", arch


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    """严格按 major.minor.patch 数值比较（忽略预发布后缀）。"""
    def parts(v: str):
        head = v.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
        out = []
        for x in head.split(".")[:3]:
            try:
                out.append(int(x))
            except ValueError:
                out.append(0)
        while len(out) < 3:
            out.append(0)
        return tuple(out)
    try:
        return parts(latest) > parts(current)
    except Exception:
        return False


def check_for_update(timeout: float = 8.0) -> Optional[UpdateInfo]:
    """查询更新。无更新/出错/开发环境均返回 None（绝不抛异常）。"""
    if not getattr(sys, "frozen", False):
        return None  # 源码运行不自更新
    target, arch = _target_arch()
    path = f"/updates/{PRODUCT_ID}/{CHANNEL}/{target}/{arch}/{APP_VERSION}"
    for base in BASE_URLS:
        req = urllib.request.Request(base + path, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 204:
                    return None
                data = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 204:
                return None
            if 400 <= e.code < 500:
                return None
            continue
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
        else:
            version = str(data.get("version") or "").strip()
            url = str(data.get("url") or "").strip()
            if not version or not is_newer(version) or not url.lower().startswith("https://"):
                return None
            return UpdateInfo(
                version=version,
                notes=str(data.get("notes") or ""),
                url=url,
                sha256=str(data.get("sha256") or "").strip().lower(),
                size=int(data.get("size") or 0),
                pub_date=str(data.get("pub_date") or ""),
            )
    return None


def download_update(info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None,
                    cancel_check: Optional[Callable[[], bool]] = None) -> Optional[str]:
    """下载更新到临时文件，校验 SHA-256，返回新 exe 路径；失败/取消返回 None。"""
    if sys.platform != "win32":
        log_warning(T("当前平台暂不支持应用内自动替换，请下载新版安装包"), "Updater")
        return None
    exe_path = sys.executable
    exe_dir = os.path.dirname(exe_path)
    new_path = os.path.join(exe_dir, "积磊截图.new.exe")
    tmp_path = new_path + ".part"
    try:
        req = urllib.request.Request(info.url, headers={"User-Agent": "JileiScreenshot-Updater"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_path, "wb") as f:
            total = info.size or int(resp.headers.get("Content-Length") or 0)
            done = 0
            digest = hashlib.sha256()
            while True:
                if cancel_check and cancel_check():
                    f.close()
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    return None
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if info.sha256 and digest.hexdigest().lower() != info.sha256:
            log_warning(T("更新包校验失败（SHA-256 不一致），已中止"), "Updater")
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return None
        os.replace(tmp_path, new_path)
        return new_path
    except Exception as e:
        log_warning(T("下载更新失败: {e}", e=e), "Updater")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None


def install_and_restart(new_exe: str) -> bool:
    """把新版本顶到当前 exe 的位置并重启。返回 False 表示无法安装。

    为什么不再用批处理：原先写一个 .bat「等本进程退出 → move /Y 覆盖」，但 bat 里带
    中文路径（积磊截图.exe），脚本按 GBK 写出、cmd 又按 UTF-8 解析，路径直接失效，
    move 静默失败、软件版本不升——这就是「点了立即更新还是 2.6.2」的原因。

    Windows 不允许覆盖/删除**运行中**的 exe，但允许**重命名**运行中的 exe，所以
    整个替换在进程内直接完成：旧 exe 改名 → 新 exe 就位 → 启动新版 → 退出本进程。
    改名后的旧文件此刻仍被占用删不掉，留到下次启动由 cleanup_previous_install() 清理。
    """
    if sys.platform != "win32":
        return False
    exe_path = sys.executable
    if not os.path.isfile(new_exe):
        log_warning(T("找不到已下载的新版本文件，无法自动安装"), "Updater")
        return False

    stale = exe_path + ".old"
    try:
        if os.path.exists(stale):
            os.remove(stale)
        os.replace(exe_path, stale)        # 运行中的 exe 只能改名，不能覆盖
        try:
            os.replace(new_exe, exe_path)  # 新版本就位
        except OSError:
            os.replace(stale, exe_path)    # 回滚，绝不能让软件文件消失
            raise
    except OSError as e:
        log_warning(T("替换程序文件失败: {e}", e=e), "Updater")
        return False

    try:
        subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path), close_fds=True)
    except OSError as e:
        # 新版已经就位，只是没能自动拉起：让用户手动重启即可，不再回滚
        log_warning(T("启动新版本失败: {e}", e=e), "Updater")
        return False

    log_info(T("更新已就绪，应用即将退出并重启"), "Updater")
    from PySide6.QtWidgets import QApplication
    QApplication.quit()
    return True


def cleanup_previous_install() -> None:
    """启动时清理上一次应用内更新留下的旧 exe 与下载残留。

    上一次更新后，旧 exe 被改名为 ``<exe>.old`` 且当时仍被占用；此刻进程已经重启，
    这些文件不再被锁，可以安全删除。纯清理动作，失败不影响启动。
    """
    if not getattr(sys, "frozen", False):
        return
    exe_dir = os.path.dirname(sys.executable)
    for path in (
        sys.executable + ".old",
        os.path.join(exe_dir, "积磊截图.new.exe"),
        os.path.join(exe_dir, "积磊截图.new.exe.part"),
    ):
        if not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError as e:
            log_warning(T("清理更新残留失败: {e}", e=e), "Updater")

