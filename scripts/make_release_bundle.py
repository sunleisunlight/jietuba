# -*- coding: utf-8 -*-
"""积磊截图 Windows 发布四件套一键打包（发布模式对齐 dizhi-tool）。

产出到 dist/release/（平铺，全部在同一个目录）：
  ① 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>.exe        控制中心角色：Updater（artifact）
  ② 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>.exe.sig    ① 的 minisign 签名，角色：Signature
  ③ 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>-setup.exe  首次安装包，角色：安装包
  ④ v<版本>-<YYMMDD>-更新说明.txt                        发布信息 TXT，角色：更新说明
  另有 ⑤ 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>.sha256：只作本地校验记录，
  写在 `dist/`（不在 `release/` 内），**不要上传**（控制中心不接受 .sha256，
  会报「Tauri 发布不支持这些文件」）。

为什么必须是这四个角色（不能只传一个 exe）：
  控制中心 services/release_intake_service.py 的发布前检查硬性要求
  updater artifact + 与 artifact 同名的 .sig + 首次安装包 + 能解析出更新说明的 TXT；
  storage/repositories/releases.py 再校验 .sig 名称必须等于「artifact 文件名 + .sig」。
  Windows 下安装包与 updater 都是 .exe，控制中心靠文件名里是否含 setup / installer 区分，
  所以 ① 的文件名里绝对不能出现 setup。

签名：复用 dizhi-tool 同一把 Tauri updater 私钥（~/.tauri/sunget-updater-20260825.key，
口令以 DPAPI 存于同目录 .password.dpapi），通过 `tauri signer sign` 生成 .sig。
私钥口令只以环境变量传给子进程，绝不写入仓库、命令行参数或日志。

用法：
  python scripts/make_release_bundle.py --build
  python scripts/make_release_bundle.py --notes-file docs/releases/release-notes.md
  python scripts/make_release_bundle.py --notes "- 新增积磊账号与会员体系"
版本号始终从 main/main_app.py 的 APP_VERSION 静态解析（不 import，避免 PySide 副作用）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
OUT = DIST / "release"
EXE_NAME = "积磊截图.exe"
PRODUCT_ID = "jilei-screenshot"

# Tauri updater 私钥（与 dizhi-tool / 其它积磊产品共用同一把）
KEY_PATH = Path(os.environ.get("JILEI_TAURI_KEY") or (Path.home() / ".tauri" / "sunget-updater-20260825.key"))
PASSWORD_PATH = KEY_PATH.with_suffix(".password.dpapi")
# 私钥内容哈希：与 ~/.tauri/Invoke-SunGetWindowsRelease.ps1 里的常量一致，
# 防止拿错密钥签出无人可验的包。
EXPECTED_KEY_SHA256 = "241a32e628ac1892b2d1812f031253a201558f8128c171405201856eb954dd5a"

# tauri CLI：优先环境变量，其次 PATH，最后回退到 dizhi-tool 的 node_modules
FALLBACK_TAURI_CLI = Path(r"D:\Codex\dizhi-tool\node_modules\.bin\tauri.cmd")


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


def resolve_tauri_cli() -> Path:
    override = os.environ.get("JILEI_TAURI_CLI", "").strip()
    if override:
        candidate = Path(override)
        if candidate.exists():
            return candidate
        raise RuntimeError(f"JILEI_TAURI_CLI 指向的文件不存在：{candidate}")
    found = shutil.which("tauri")
    if found:
        return Path(found)
    if FALLBACK_TAURI_CLI.exists():
        return FALLBACK_TAURI_CLI
    raise RuntimeError(
        "找不到 tauri CLI，无法生成 .sig。请安装 @tauri-apps/cli，"
        "或用 JILEI_TAURI_CLI 指定 tauri 可执行文件路径。"
    )


def decrypt_key_password() -> str:
    """用 DPAPI 解出私钥口令。

    口令文件是 PowerShell `ConvertFrom-SecureString` 的产物（十六进制 DPAPI 密文），
    只能由当前 Windows 用户解密。这里直接调 crypt32 的 CryptUnprotectData，
    不经 PowerShell——从 PowerShell 7 里启动 powershell.exe 时 PSModulePath 会被
    继承污染，`ConvertTo-SecureString` 会加载失败。
    """
    direct = os.environ.get("JILEI_TAURI_KEY_PASSWORD", "").strip()
    if direct:
        return direct
    if os.name != "nt":
        raise RuntimeError("只有 Windows 支持 DPAPI 解私钥口令，请用 JILEI_TAURI_KEY_PASSWORD 传入口令。")
    if not PASSWORD_PATH.exists():
        raise RuntimeError(f"找不到私钥口令文件：{PASSWORD_PATH}")

    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    blob = bytes.fromhex(PASSWORD_PATH.read_text(encoding="utf-8").strip())
    buffer = ctypes.create_string_buffer(blob, len(blob))
    blob_in = DATA_BLOB(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError(f"CryptUnprotectData 解密口令失败（错误码 {ctypes.get_last_error()}）")
    try:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
    password = raw.decode("utf-16-le").rstrip("\x00")
    if not password:
        raise RuntimeError("私钥口令解密结果为空")
    return password


def sign_artifact(artifact: Path) -> Path:
    """生成 <artifact>.sig（minisign / Tauri updater 签名）。"""
    if not KEY_PATH.exists():
        raise RuntimeError(f"找不到 Tauri updater 私钥：{KEY_PATH}")
    actual = sha256_of(KEY_PATH)
    if actual != EXPECTED_KEY_SHA256:
        raise RuntimeError(f"私钥 SHA-256 不匹配，拒绝签名：{actual}")
    tauri_cli = resolve_tauri_cli()
    sig_path = artifact.with_name(artifact.name + ".sig")
    if sig_path.exists():
        sig_path.unlink()
    env = dict(os.environ)
    env["TAURI_SIGNING_PRIVATE_KEY_PASSWORD"] = decrypt_key_password()
    result = subprocess.run(
        [str(tauri_cli), "signer", "sign", "-f", str(KEY_PATH), str(artifact)],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    if result.returncode != 0 or not sig_path.exists() or sig_path.stat().st_size == 0:
        raise RuntimeError(f"签名失败：{result.stderr.strip() or result.stdout.strip()}")
    return sig_path


def collect_notes_lines(raw: str) -> list[str]:
    """把用户给的说明整理成控制中心能解析的「- 」条目。

    控制中心 storage/common.py::parse_release_info_txt() 的规则：
    独立一行「更新说明」，其后每行以「- 」开头。
    """
    lines: list[str] = []
    for line in str(raw or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("- "):
            lines.append(text[2:].strip())
        elif text.startswith("#") or text.startswith("###"):
            continue
        else:
            lines.append(text)
    return lines


def build_notes_text(version: str, date: str, target: str, arch: str, notes: list[str]) -> str:
    body = "\n".join(f"- {item}" for item in notes)
    return (
        f"积磊截图 v{version}\n"
        f"\n"
        f"Product ID: {PRODUCT_ID}\n"
        f"版本: {version}\n"
        f"通道: stable\n"
        f"target: {target}\n"
        f"release arch: {arch}\n"
        f"日期: {date}\n"
        f"\n"
        f"更新说明\n"
        f"{body}\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="打包前先运行 build_with_ocr_onefile.py")
    ap.add_argument("--notes", default="", help="更新说明（每行一条，可带或不带「- 」前缀）")
    ap.add_argument("--notes-file", default="", help="从文件读取更新说明（Markdown 也行）")
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

    raw_notes = args.notes
    if args.notes_file:
        notes_path = Path(args.notes_file)
        if not notes_path.is_absolute():
            notes_path = REPO / notes_path
        if not notes_path.exists():
            print(f"!! 找不到更新说明文件：{notes_path}")
            return 1
        raw_notes = notes_path.read_text(encoding="utf-8")
    notes = collect_notes_lines(raw_notes)
    if not notes:
        print("!! 更新说明为空。控制中心要求 TXT 能解析出「- 」条目，请用 --notes 或 --notes-file 提供。")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*"):
        if p.is_file():
            p.unlink()

    # ① updater artifact（文件名里不能出现 setup / installer）
    artifact = OUT / f"{stem}.exe"
    shutil.copy2(exe, artifact)

    # ② 首次安装包：与 ① 是同一份 onefile exe，只靠文件名让控制中心识别成安装包角色
    installer = OUT / f"{stem}-setup.exe"
    shutil.copy2(exe, installer)

    # ③ 签名：必须叫「artifact 文件名 + .sig」
    sig = sign_artifact(artifact)

    # ④ 发布信息 TXT
    notes_txt = OUT / f"v{version}-{date}-更新说明.txt"
    notes_txt.write_text(
        build_notes_text(version, date, "windows", "x86_64" if args.arch == "x64" else "aarch64", notes),
        encoding="utf-8",
    )

    # ⑤ 本地校验记录：写到 dist/ 而不是 dist/release/，避免被顺手拖进发布页
    #    （控制中心 Tauri 白名单没有 .sha256，拖进去会报「Tauri 发布不支持这些文件」）
    digest = sha256_of(artifact)
    sha_file = DIST / f"{stem}.sha256"
    sha_file.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")

    print("=" * 60)
    print("发布四件套已生成（dist/release/ 里就是发布页要传的全部文件）：", OUT)
    for p in (artifact, sig, installer, notes_txt):
        print(f"  {p.name}  ({p.stat().st_size:,} bytes)")
    print(f"  本地校验记录（不在 release/ 内，勿上传）: {sha_file}")
    print(f"SHA-256（{artifact.name}）: {digest}")
    print("=" * 60)
    print("下一步：在控制中心发布页把这四个文件一次拖进去（exe / exe.sig / -setup.exe / 更新说明.txt）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())