#!/usr/bin/env bash
# Jietuba macOS 公证脚本。
#
# 前置条件（配置后一键执行）：
#   - 已用 Developer ID Application 证书签名（build_macos.py 会自动选择）
#   - 已配置 notarytool 凭据，任选其一：
#       xcrun notarytool store-credentials "jietuba" \
#           --apple-id "you@example.com" --team-id "XXXXXX" --password "app-specific-password"
#     （或 --api-key ... --api-key-id ... --api-key-issuer-id ...）
#
# 用法: ./scripts/notarize_macos.sh [profile名，默认 jietuba]
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${1:-jietuba}"
APP="dist/Jietuba.app"

# 版本唯一源：main/main_app.py 的 APP_VERSION（经 scripts/version_utils.py 读取）。
# 禁止在此写死版本号——必须与 package_macos.sh 产出的 DMG 名一致。
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
VERSION="$("$PY" scripts/version_utils.py)"
if [ -z "$VERSION" ]; then
  echo "!! 无法从 main/main_app.py 读取 APP_VERSION"
  exit 1
fi
DMG="dist/Jietuba-${VERSION}-arm64.dmg"

if [ ! -f "$DMG" ]; then
  echo "!! 找不到 DMG: $DMG（请先运行 scripts/package_macos.sh）"
  exit 1
fi

if ! xcrun notarytool --version >/dev/null 2>&1; then
  echo "!! xcrun notarytool 不可用（需要 Xcode 命令行工具）"
  exit 1
fi

echo "==> 提交公证（等待结果）"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait

echo "==> 装订（staple）"
xcrun stapler staple "$APP"
xcrun stapler staple "$DMG" || true

echo "==> 验证"
xcrun stapler validate "$APP"
xcrun stapler validate "$DMG"
spctl -a -vv "$APP" || echo "!! spctl 评估不通过（可能未装订完成，稍后重试）"
echo "==> 公证完成"
