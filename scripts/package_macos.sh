#!/usr/bin/env bash
# Jietuba macOS 打包 + 签名 + DMG。
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

echo "==> 构建 .app（版本 $VERSION）"
"$PY" build_macos.py

echo "==> 制作 DMG"
DMG="dist/Jietuba-${VERSION}-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "Jietuba" -srcfolder dist/Jietuba.app \
  -ov -format UDZO "$DMG"
hdiutil verify "$DMG"

echo "==> 完成: $DMG"
ls -lh "$DMG"
