#!/usr/bin/env bash
# Jietuba macOS 打包 + 签名 + DMG。
# 用法: ./scripts/package_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 构建 .app"
.venv/bin/python build_macos.py

echo "==> 制作 DMG"
DMG="dist/Jietuba-2.0.6-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "Jietuba" -srcfolder dist/Jietuba.app \
  -ov -format UDZO "$DMG"
hdiutil verify "$DMG"

echo "==> 完成: $DMG"
ls -lh "$DMG"
