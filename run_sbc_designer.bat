@echo off
rem Start SBC Designer from a source checkout (run install_windows.bat once first).
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Virtual environment not found - running install_windows.bat first.
  call install_windows.bat || exit /b 1
)
start "" .venv\Scripts\pythonw.exe -m sbc_designer %*
