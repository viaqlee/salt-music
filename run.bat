@echo off
rem Start Salt Music from sources (development). Creates .venv on first run.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Creating .venv ...
    py -3 -m venv .venv || python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :eof
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
goto :eof
:nopython
echo Python 3.12+ is required: winget install Python.Python.3.14
pause
