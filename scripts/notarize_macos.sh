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
DMG="dist/Jietuba-2.0.6-arm64.dmg"

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
