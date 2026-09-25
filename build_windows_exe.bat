@echo off
rem Build a stand-alone Windows application in dist\SBC_Designer\SBC_Designer.exe
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call install_windows.bat || exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging\sbc_designer.spec || exit /b 1
echo Built dist\SBC_Designer\SBC_Designer.exe
