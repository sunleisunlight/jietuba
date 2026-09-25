#!/usr/bin/env bash
# Jietuba macOS 环境准备：工具链检测 + venv + Python 依赖 + Rust 扩展。
# 用法: ./scripts/setup_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 工具链检测"
python3 --version
uname -m
rustc --version || echo "!! rustc 未安装（需要 Rust toolchain）"
cargo --version || echo "!! cargo 未安装"

if [ ! -d .venv ]; then
  echo "==> 创建 .venv (Python 3.11)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 安装 Python 依赖（Mac 条件依赖，跳过 pywin32/comtypes）"
pip install -r requirements.txt -r requirements-dev.txt

echo "==> 构建 Rust 扩展 (arm64 wheel)"
mkdir -p /tmp/jietuba_wheels
for crate in longstitch pyclipboard ppocr_rust gifrecorder; do
  (cd "rust_libs/$crate" && maturin build --release --out /tmp/jietuba_wheels)
done
pip install --force-reinstall /tmp/jietuba_wheels/*arm64*.whl

echo "==> 完成。源码运行: cd main && python main_app.py"
