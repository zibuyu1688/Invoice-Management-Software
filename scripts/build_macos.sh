#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/generate_app_icons.py

rm -rf build/蜀丞票管 dist/蜀丞票管 dist/蜀丞票管.app
rm -f dist/蜀丞票管-macos.zip

pyinstaller --noconfirm --clean --windowed --name 蜀丞票管 \
  --icon assets/icons/shucheng.icns \
  --add-data "app/templates:app/templates" \
  --add-data "app/static:app/static" \
  --collect-submodules webview \
  launcher.py

# Fail the build if runtime data files were accidentally bundled.
if find dist/蜀丞票管.app -type f \( -name "invoice.db" -o -name "invoice_export_*.xlsx" -o -name "*.ofd" -o -name "*.pdf" \) | grep -q .; then
  echo "Error: build package contains runtime data files (db/exports/attachments)."
  exit 1
fi

ditto -c -k --sequesterRsrc --keepParent dist/蜀丞票管.app dist/蜀丞票管-macos.zip

echo "Build complete: dist/蜀丞票管.app"
echo "Delivery package: dist/蜀丞票管-macos.zip"
