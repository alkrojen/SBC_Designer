@echo off
rem Create a virtual environment and install SBC Designer's dependencies.
rem Requires Python 3.10 - 3.12 (64-bit) from python.org on the PATH.
cd /d "%~dp0"
py -3 -m venv .venv || python -m venv .venv || exit /b 1
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt || exit /b 1
echo.
echo Installed. Start the application with run_sbc_designer.bat
echo Run the unit tests with: .venv\Scripts\python.exe -m pytest
