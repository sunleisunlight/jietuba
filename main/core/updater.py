# -*- coding: utf-8 -*-
"""积磊截图自动更新器（Python onefile 版）。

与积磊控制中心的 Tauri 更新清单同一套接口合同：
    GET /updates/jilei-screenshot/stable/<target>/<arch>/<current_version>
- 无更新：HTTP 204
- 有更新：JSON {version, notes, pub_date, url, sha256, size, displayVersion}

安全：强制 HTTPS；下载后用服务端清单里的 SHA-256 做完整性校验（清单本身经
HTTPS 传输，SHA-256 防下载损坏/被篡改）。Windows 下 onefile exe 运行时被锁定，
采用「下载到 .new.exe → 启动批处理等待本进程退出 → 覆盖 → 重启」的标准替换法。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
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
    """启动替换器并退出当前进程。返回 False 表示无法安装。"""
    if sys.platform != "win32":
        return False
    exe_path = sys.executable
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "jileiscreenshot_update.bat")
    # 轮询等待本进程退出 → 覆盖 exe → 重启 → 自删批处理
    content = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul 2>&1\r\n'
        "if not errorlevel 1 (\r\n  ping 127.0.0.1 -n 2 >nul\r\n  goto wait\r\n)\r\n"
        f'move /Y "{new_exe}" "{exe_path}" >nul 2>&1\r\n'
        f'if exist "{new_exe}" goto wait\r\n'
        f'start "" "{exe_path}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
    )
    try:
        with open(bat, "w", encoding="gbk", errors="ignore") as f:
            f.write(content)
        import subprocess
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["cmd.exe", "/c", bat], close_fds=True, creationflags=creationflags)
        log_info(T("更新已就绪，应用即将退出并重启"), "Updater")
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
        return True
    except Exception as e:
        log_warning(T("启动更新失败: {e}", e=e), "Updater")
        return False
