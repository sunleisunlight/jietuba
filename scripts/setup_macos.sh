#!/usr/bin/env bash
# 积磊截图 macOS 环境准备：工具链检测 + venv + Python 依赖 + Rust 扩展。
# 用法: ./scripts/setup_macos.sh
#
# 项目只支持 Python 3.11 与 Apple Silicon (arm64)。检测不通过时直接停止，
# 绝不用错误版本的 Python / 错误架构继续生成不可用的软件。
set -euo pipefail
cd "$(dirname "$0")/.."

REQUIRED_PY="3.11"

echo "==> 架构检测"
ARCH="$(uname -m)"
echo "uname -m: $ARCH"
if [ "$ARCH" != "arm64" ]; then
  echo "!! 当前架构为 ${ARCH}，本项目 macOS 正式目标只有 Apple Silicon (arm64)。"
  echo "   请在 Apple Silicon 机器上执行本脚本。"
  exit 1
fi

echo "==> Python 检测（必须 ${REQUIRED_PY}）"
PY_BIN="${PYTHON:-}"
if [ -z "$PY_BIN" ]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PY_BIN="python3.11"
  elif command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  else
    echo "!! 未找到 python3（需要 Python ${REQUIRED_PY}）"
    exit 1
  fi
fi
PY_VER="$("$PY_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "$PY_BIN -> Python $PY_VER"
if [ "$PY_VER" != "$REQUIRED_PY" ]; then
  echo "!! 需要 Python ${REQUIRED_PY}，当前为 ${PY_VER}（${PY_BIN}）"
  echo "   安装示例: brew install python@3.11"
  echo "   或指定解释器: PYTHON=/path/to/python3.11 ./scripts/setup_macos.sh"
  exit 1
fi

echo "==> Rust 工具链检测"
if ! command -v rustc >/dev/null 2>&1; then
  echo "!! 未安装 rustc，需要 Rust toolchain（https://rustup.rs）后再运行"
  exit 1
fi
rustc --version
cargo --version

# macOS 27 SDK 的 .tbd 里包含当前 CLT 链接器不认识的 arm64e.x1-macos，
# Rust 链接会报 “unknown architecture / malformed file”。系统同时装了
# 15.4 SDK 时自动回退，避免用户手工设置 SDKROOT。
if [ -z "${SDKROOT:-}" ]; then
  SDK_VERSION="$(xcrun --show-sdk-version 2>/dev/null || true)"
  SDK15="$(xcode-select -p)/SDKs/MacOSX15.4.sdk"
  if [ "${SDK_VERSION}" = "27.0" ] && [ -d "${SDK15}" ]; then
    export SDKROOT="${SDK15}"
    echo "==> macOS 27 SDK 与当前链接器不兼容，回退到 ${SDKROOT}"
  fi
fi
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"

if [ ! -d .venv ]; then
  echo "==> 创建 .venv (Python ${REQUIRED_PY})"
  "$PY_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 已有 .venv 可能由别的 Python 创建，继续用会产出错误的包
VENV_VER="$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$VENV_VER" != "$REQUIRED_PY" ]; then
  echo "!! .venv 使用 Python ${VENV_VER}，必须为 ${REQUIRED_PY}。"
  echo "   请删除后重试: rm -rf .venv"
  exit 1
fi

echo "==> 安装 Python 依赖（Mac 条件依赖，跳过 pywin32/comtypes）"
pip install -r requirements.txt -r requirements-dev.txt

echo "==> 构建 Rust 扩展 (arm64 wheel)"
WHEEL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jilei-screenshot-wheels.XXXXXX")"
for crate in longstitch pyclipboard ppocr_rust gifrecorder; do
  (cd "rust_libs/$crate" && maturin build --locked --release --out "$WHEEL_DIR")
done
pip install --force-reinstall "$WHEEL_DIR"/*arm64*.whl
echo "本轮原生 wheels 保留在: $WHEEL_DIR"

echo "==> 验证四个 Rust 扩展均可导入"
python - <<'PY'
import importlib
for name in ("gifrecorder", "longstitch", "pyclipboard", "ppocr_rust"):
    module = importlib.import_module(name)
    print(f"  [OK] {name}: {getattr(module, '__file__', '?')}")
PY

echo "==> 完成。源码运行: cd main && python main_app.py"
