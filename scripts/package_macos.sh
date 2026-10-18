#!/usr/bin/env bash
# 积磊截图 macOS 打包 + 签名 + DMG。
# 用法: ./scripts/package_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# 版本唯一源：main/main_app.py 的 APP_VERSION（经 scripts/version_utils.py 读取）。
# 禁止在此写死版本号——DMG 文件名、Info.plist、应用内版本必须始终一致。
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
VERSION="$("$PY" scripts/version_utils.py)"
if [ -z "$VERSION" ]; then
  echo "!! 无法从 main/main_app.py 读取 APP_VERSION"
  exit 1
fi

echo "==> 构建 .app（版本 ${VERSION}）"
"$PY" build_macos.py

echo "==> 制作 DMG"
DMG="dist/积磊截图-${VERSION}-arm64.dmg"
if [ -e "$DMG" ]; then
  echo "!! 已存在 ${DMG}，拒绝覆盖历史产物。"
  exit 1
fi
"$PY" -c 'import sys; from pathlib import Path; sys.path.insert(0, "scripts"); from macos_release import make_dmg; make_dmg(Path("dist/积磊截图.app"), Path(sys.argv[1]))' "$DMG"

echo "==> 完成: $DMG"
ls -lh "$DMG"
