# -*- coding: utf-8 -*-
"""macOS 打包契约（静态检查，Windows CI 亦可执行）。

目的：``APP_VERSION`` 从 2.4.0 升到 2.5.0 时，任何人都不需要再手动修改
``build_macos.py`` / ``jietuba_macos.spec`` / ``scripts/*.sh`` 里的版本号，
也不会再出现 Mac 打包漏掉 ppocr_rust / OCR 模型的情况。

这些检查只读文本与 ast，不依赖真实 macOS，也不启动 PyInstaller。
"""
import ast
import importlib.util
import re
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[2]
SCRIPTS = REPOSITORY / "scripts"

MAC_VERSION_FILES = (
    "build_macos.py",
    "jietuba_macos.spec",
    "scripts/package_macos.sh",
    "scripts/notarize_macos.sh",
)

OCR_MODELS = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx")


def _read(rel: str) -> str:
    return (REPOSITORY / rel).read_text(encoding="utf-8")


def _load_version_utils():
    spec = importlib.util.spec_from_file_location(
        "jietuba_version_utils", SCRIPTS / "version_utils.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def app_version() -> str:
    return _load_version_utils().read_app_version()


# ── 1. APP_VERSION 能正确读取 ──────────────────────────────────────────────

def test_app_version_is_three_segment_semver(app_version):
    assert re.fullmatch(r"\d+\.\d+\.\d+", app_version), app_version


def test_version_utils_reads_main_app_without_importing_it():
    """必须 ast 静态解析，禁止 import main_app.py（会拉入 PySide6 副作用）。"""
    source = _read("scripts/version_utils.py")
    assert "ast.parse" in source
    assert not re.search(r"^\s*(from|import)\s+main_app\b", source, re.M)


def test_version_utils_agrees_with_main_app_source(app_version):
    tree = ast.parse(_read("main/main_app.py"))
    values = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    assert values == [app_version]


def test_version_utils_cli_prints_the_version(app_version):
    """CLI 是 bash 打包脚本获取版本的入口，必须存在。"""
    source = _read("scripts/version_utils.py")
    assert "__main__" in source
    assert "print(read_app_version())" in source
    assert app_version


# ── 2. Mac 构建链不再写死旧版本号 ──────────────────────────────────────────

@pytest.mark.parametrize("rel", MAC_VERSION_FILES)
def test_mac_build_chain_has_no_stale_hardcoded_version(rel):
    source = _read(rel)
    assert "2.0.6" not in source, f"{rel} 仍写死旧版本号 2.0.6"
    assert re.search(r"CFBundle.*206\b", source) is None, f"{rel} 仍有 206 版本"


@pytest.mark.parametrize("rel", MAC_VERSION_FILES)
def test_mac_build_chain_reads_the_single_version_source(rel):
    source = _read(rel)
    if rel.endswith(".sh"):
        assert "scripts/version_utils.py" in source, rel
    else:
        assert "read_app_version" in source, rel


def test_mac_spec_and_scripts_derive_dmg_and_plist_from_app_version(app_version):
    spec = _read("jietuba_macos.spec")
    assert '"CFBundleShortVersionString": APP_VERSION' in spec
    assert '"CFBundleVersion": APP_VERSION' in spec
    for script in ("scripts/package_macos.sh", "scripts/notarize_macos.sh"):
        source = _read(script)
        assert "Jietuba-${VERSION}-arm64.dmg" in source, script
    assert app_version


# ── 3/4. ppocr_rust 与 OCR 模型必须是 Mac 正式构建的一部分 ─────────────────

def test_mac_spec_does_not_exclude_ppocr_rust():
    spec = _read("jietuba_macos.spec")
    excludes_block = spec.split("excludes = [", 1)[1].split("]", 1)[0]
    assert "ppocr_rust" not in excludes_block
    # 并且必须作为隐藏导入参与打包
    hidden_block = spec.split("hiddenimports = [", 1)[1].split("]", 1)[0]
    assert '"ppocr_rust"' in hidden_block


def test_mac_spec_bundles_onnxruntime_dylib():
    spec = _read("jietuba_macos.spec")
    assert "libonnxruntime" in spec
    assert "collect_dynamic_libs(\"ppocr_rust\")" in spec
    assert "binaries=binaries" in spec


@pytest.mark.parametrize("rel", ("jietuba_macos.spec", "build_macos.py"))
def test_mac_build_treats_ocr_models_as_required(rel):
    source = _read(rel)
    for model in OCR_MODELS:
        assert model in source, f"{rel} 未引用 {model}"


def test_mac_build_fails_instead_of_skipping_ocr():
    build = _read("build_macos.py")
    # 不允许再出现"无 OCR 也构建成功"的可选路径
    assert "SKIP(无OCR)" not in build
    assert "构建为无 OCR 版本" not in build
    # 缺少模型必须直接失败
    assert "sys.exit(1)" in build
    # ppocr_rust 在资源验证里是必需项
    assert '("ppocr_rust", True)' in build
    # Info.plist 版本必须与 APP_VERSION 比对
    assert "CFBundleShortVersionString" in build
    assert "CFBundleVersion" in build


def test_mac_build_checks_native_dependencies_with_otool():
    build = _read("build_macos.py")
    assert "otool" in build
    assert "libonnxruntime" in build or "onnxruntime" in build or "_app_contains" in build


# ── 5. 最低系统版本与真实实现一致 ─────────────────────────────────────────

def test_mac_min_os_reflects_screencapturekit_requirement():
    spec = _read("jietuba_macos.spec")
    match = re.search(r'"LSMinimumSystemVersion":\s*"([\d.]+)"', spec)
    assert match, "spec 必须声明 LSMinimumSystemVersion"
    major, minor = (int(x) for x in match.group(1).split(".")[:2])
    # GIF 录制依赖 ScreenCaptureKit（macOS 12.3+）
    assert (major, minor) >= (12, 3), match.group(1)


# ── 6. setup_macos.sh 必须锁定 Python 3.11 与 arm64 ────────────────────────

def test_setup_macos_enforces_python_311():
    source = _read("scripts/setup_macos.sh")
    assert "3.11" in source
    assert "python3.11" in source
    # 版本不符必须报错退出，而不是继续
    assert "exit 1" in source


def test_setup_macos_checks_architecture_and_verifies_extensions():
    source = _read("scripts/setup_macos.sh")
    assert "uname -m" in source
    assert "arm64" in source
    for name in ("gifrecorder", "longstitch", "pyclipboard", "ppocr_rust"):
        assert name in source, name