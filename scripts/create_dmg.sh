#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

APP_PATH="dist/蜀丞票管.app"
DMG_PATH="dist/蜀丞票管.dmg"
VOLUME_NAME="蜀丞票管"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing $APP_PATH, run scripts/build_macos.sh first"
  exit 1
fi

if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "$VOLUME_NAME" \
    --window-pos 200 120 \
    --window-size 900 500 \
    --icon-size 100 \
    --app-drop-link 700 250 \
    "$DMG_PATH" \
    "$APP_PATH"
else
  hdiutil create -volname "$VOLUME_NAME" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"
fi

echo "DMG ready: $DMG_PATH"
