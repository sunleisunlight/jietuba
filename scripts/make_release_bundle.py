# -*- coding: utf-8 -*-
"""积磊截图 Windows 发布四件套一键打包（发布模式对齐 dizhi-tool）。

产出到 dist/release/（平铺，全部在同一个目录）：
  ① 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>.exe        控制中心角色：Updater（artifact）
  ② 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>.exe.sig    ① 的 minisign 签名，角色：Signature
  ③ 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>-setup.exe  首次安装包（NSIS 安装器），角色：安装包
  ④ v<版本>-<YYMMDD>-更新说明.txt                        发布信息 TXT，角色：更新说明
  另有 ⑤ 积磊截图-v<版本>-<YYMMDD>-Windows-<arch>.sha256：只作本地校验记录，
  写在 `dist/`（不在 `release/` 内），**不要上传**（控制中心不接受 .sha256，
  会报「Tauri 发布不支持这些文件」）。

dist/release/ 是**只增不删的存档**（AGENTS.md「历史发布产物一律保留」）：
每次出包只在里面新增本轮这 4 个文件，既不清空旧包、也不覆盖同名文件——旧包可能
还没被拖进控制中心发布中心，也可能正被"从目录里直接运行的软件"占用。所以四件套
先在临时目录里做完，撞名或中途失败都不会动到存档里的任何东西。

① 与 ③ 是两个不同的东西，别再混为一谈：
  ① 是 PyInstaller onefile 裸 exe，应用内自动更新下载的就是它（main/core/updater.py
     直接改名替换 exe）；它必须是裸 exe，换成安装器会让自动更新失效。
  ③ 是 NSIS 打出来的真安装器（packaging/jietuba_setup.nsi）：向导里可以选安装路径、
     装开始菜单/桌面快捷方式、写「应用和功能」卸载入口；官网下载页给新用户的是它。

为什么必须是这四个角色（不能只传一个 exe）：
  控制中心 services/release_intake_service.py 的发布前检查硬性要求
  updater artifact + 与 artifact 同名的 .sig + 首次安装包 + 能解析出更新说明的 TXT；
  storage/repositories/releases.py 再校验 .sig 名称必须等于「artifact 文件名 + .sig」。
  Windows 下安装包与 updater 都是 .exe，控制中心靠文件名里是否含 setup / installer 区分，
  所以 ① 的文件名里绝对不能出现 setup。

③ 由 makensis（NSIS 3，中文需要 Unicode 版）编译；本机可复用 Tauri 缓存里的
%LOCALAPPDATA%\\tauri\\NSIS\\makensis.exe，或用 JILEI_MAKENSIS 指定。

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

# NSIS 安装器脚本（生成「首次安装包」③）
NSIS_SCRIPT = REPO / "packaging" / "jietuba_setup.nsi"
APP_ICON = REPO / "托盘.ico"


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
    if sys.platform == "darwin":
        candidate = REPO.parent / "dizhi-tool/node_modules/.bin/tauri"
        if candidate.exists():
            return candidate
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
    for name in ("JILEI_TAURI_KEY_PASSWORD", "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"):
        if name in os.environ:
            return os.environ[name]  # 口令不做 strip；显式空口令也保持原值。
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


def resolve_makensis() -> Path:
    """定位 NSIS 编译器：环境变量 → PATH → Tauri 缓存 → 常规安装目录。"""
    override = os.environ.get("JILEI_MAKENSIS", "").strip()
    if override:
        candidate = Path(override)
        if candidate.exists():
            return candidate
        raise RuntimeError(f"JILEI_MAKENSIS 指向的文件不存在：{candidate}")

    found = shutil.which("makensis")
    if found:
        return Path(found)

    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        # 积磊其它桌面端（Tauri）自带的 NSIS，本机已存在，优先复用
        candidates.append(Path(local_appdata) / "tauri" / "NSIS" / "makensis.exe")
    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env_name, "")
        if base:
            candidates.append(Path(base) / "NSIS" / "makensis.exe")
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise RuntimeError(
        "找不到 NSIS 的 makensis，无法生成安装包。请安装 NSIS 3（或用 JILEI_MAKENSIS "
        "指定路径）；本机也可直接复用 Tauri 缓存里的 %LOCALAPPDATA%\\tauri\\NSIS\\makensis.exe。"
    )


def ensure_utf8_bom(path: Path) -> None:
    """NSIS 3 靠 BOM 判断脚本编码；缺 BOM 时中文会按本地代码页解析成乱码。"""
    data = path.read_bytes()
    if not data.startswith(b"\xef\xbb\xbf"):
        path.write_bytes(b"\xef\xbb\xbf" + data)


def build_installer(version: str, stem: str, exe: Path, out_dir: Path) -> Path:
    """用 NSIS 生成「点击安装 + 自选路径 + 快捷方式 + 卸载」的真实安装包。

    传给 makensis 的路径一律用 ASCII 临时目录：中文路径经命令行传参时受命令行
    代码页影响，容易变乱码并静默失败（应用内更新就是栽在这类编码问题上）。
    """
    if not NSIS_SCRIPT.exists():
        raise RuntimeError(f"找不到 NSIS 脚本：{NSIS_SCRIPT}")
    if not APP_ICON.exists():
        raise RuntimeError(f"找不到安装器图标：{APP_ICON}")
    makensis = resolve_makensis()

    # VIProductVersion 只接受 X.X.X.X 四段纯数字，APP_VERSION 是三段 SemVer
    numeric = [part for part in version.split("-")[0].split(".") if part.isdigit()]
    while len(numeric) < 4:
        numeric.append("0")
    file_version = ".".join(numeric[:4])

    with tempfile.TemporaryDirectory(prefix="jietuba_setup_") as stage:
        stage_dir = Path(stage)
        script = stage_dir / "setup.nsi"
        shutil.copy2(NSIS_SCRIPT, script)
        ensure_utf8_bom(script)
        staged_exe = stage_dir / "app.exe"
        staged_icon = stage_dir / "app.ico"
        staged_out = stage_dir / "setup.exe"
        shutil.copy2(exe, staged_exe)
        shutil.copy2(APP_ICON, staged_icon)

        result = subprocess.run(
            [
                str(makensis),
                f"/DAPP_VERSION={version}",
                f"/DVI_VERSION={file_version}",
                f"/DSOURCE_EXE={staged_exe}",
                f"/DICON_FILE={staged_icon}",
                f"/DOUT_FILE={staged_out}",
                str(script),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not staged_out.exists():
            detail = ((result.stdout or "") + (result.stderr or "")).strip()
            raise RuntimeError(f"NSIS 编译安装包失败：\n{detail}")

        installer = out_dir / f"{stem}-setup.exe"
        shutil.copy2(staged_out, installer)
    return installer


def ensure_names_are_new(out_dir: Path, names) -> None:
    """出包前先看这一轮的文件名在 dist/release/ 里有没有撞名，撞了就退出。

    dist/release/ 是发布产物的存档，**只增不删**（见 AGENTS.md「历史发布产物一律保留」）：
    旧包可能还没被拖进控制中心发布中心，也可能正被"从目录里直接运行的软件"占用，
    所以这里既不清空旧文件、也不覆盖同名文件。撞名说明这一版已经出过一次包，
    写下去就会覆盖掉手上那份，直接报错让人来确认更安全。
    """
    existing = [name for name in names if (out_dir / name).exists()]
    if existing:
        raise RuntimeError(
            "dist/release/ 里已经有同名的发布产物，拒绝覆盖：\n  "
            + "\n  ".join(existing)
            + "\n旧包一律原地保留（AGENTS.md「历史发布产物一律保留」）。"
            "如果确认要重新出同一版，请先自行把那几个文件挪到别处。"
        )


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

    if sys.platform == "darwin":
        from macos_release import make_macos_bundle
        return make_macos_bundle(args)

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

    artifact_name = f"{stem}.exe"
    installer_name = f"{stem}-setup.exe"
    sig_name = f"{artifact_name}.sig"
    notes_name = f"v{version}-{date}-更新说明.txt"
    # 存档目录只增不删：本轮文件名已有同名文件就直接退出，绝不覆盖
    ensure_names_are_new(OUT, (artifact_name, installer_name, sig_name, notes_name))

    # 先在一个临时目录里把四件套整整齐齐做完，最后一步才搬进 dist/release/：
    # 中途失败时存档目录里不会留下半套产物（半套产物既不能发布，又因为"不删旧包"
    # 只能靠人工收拾）。
    staging = Path(tempfile.mkdtemp(prefix="jilei_release_"))
    try:
        # ① updater artifact（文件名里不能出现 setup / installer）
        artifact = staging / artifact_name
        shutil.copy2(exe, artifact)

        # ② 首次安装包：真实的 NSIS 安装器（向导选路径 + 快捷方式 + 卸载），
        #    与控制中心「首次安装包」角色对应；官网下载页给新用户的就是它。
        print("==> 编译安装包（NSIS）…")
        installer = build_installer(version, stem, exe, staging)

        # ③ 签名：必须叫「artifact 文件名 + .sig」
        sig = sign_artifact(artifact)

        # ④ 发布信息 TXT
        notes_txt = staging / notes_name
        notes_txt.write_text(
            build_notes_text(version, date, "windows", "x86_64" if args.arch == "x64" else "aarch64", notes),
            encoding="utf-8",
        )

        planned = (artifact, sig, installer, notes_txt)
        for path in planned:
            shutil.move(str(path), str(OUT / path.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    published_artifact = OUT / artifact_name

    # ⑤ 本地校验记录：写到 dist/ 而不是 dist/release/，避免被顺手拖进发布页
    #    （控制中心 Tauri 白名单没有 .sha256，拖进去会报「Tauri 发布不支持这些文件」）
    digest = sha256_of(published_artifact)
    sha_file = DIST / f"{stem}.sha256"
    sha_file.write_text(f"{digest}  {published_artifact.name}\n", encoding="utf-8")

    print("=" * 60)
    print("发布四件套已生成（dist/release/ 里就是发布页要传的全部文件）：", OUT)
    for path in (published_artifact, OUT / sig_name, OUT / installer_name, OUT / notes_name):
        print(f"  {path.name}  ({path.stat().st_size:,} bytes)")
    print(f"  本地校验记录（不在 release/ 内，勿上传）: {sha_file}")
    print(f"SHA-256（{published_artifact.name}）: {digest}")
    print("=" * 60)
    print("控制中心发布页一次拖入本轮这 4 个文件即可；release/ 里其它版本的文件是旧包存档，别删也别传。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
