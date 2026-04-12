@echo off
setlocal
cd /d %~dp0\..

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate
pip install -r requirements.txt
python scripts\generate_app_icons.py

if exist build\蜀丞票管 rmdir /s /q build\蜀丞票管
if exist dist\蜀丞票管 rmdir /s /q dist\蜀丞票管
if exist dist\蜀丞票管.exe del /f /q dist\蜀丞票管.exe
if exist dist\蜀丞票管-windows.zip del /f /q dist\蜀丞票管-windows.zip

pyinstaller --noconfirm --clean --windowed --name 蜀丞票管 ^
  --icon assets\icons\shucheng.ico ^
  --add-data "app/templates;app/templates" ^
  --add-data "app/static;app/static" ^
  launcher.py

powershell -NoProfile -ExecutionPolicy Bypass -Command "$bad = Get-ChildItem -Path 'dist\蜀丞票管' -Recurse -File | Where-Object { $_.Name -eq 'invoice.db' -or $_.Name -like 'invoice_export_*.xlsx' -or $_.Extension -in '.ofd','.pdf' }; if ($bad) { Write-Host 'Error: build package contains runtime data files (db/exports/attachments).'; $bad | ForEach-Object { Write-Host $_.FullName }; exit 1 }"
if errorlevel 1 exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\蜀丞票管\*' -DestinationPath 'dist\蜀丞票管-windows.zip' -Force"

echo.
echo Build complete. EXE is in dist\蜀丞票管\蜀丞票管.exe
echo Delivery package: dist\蜀丞票管-windows.zip
pause
