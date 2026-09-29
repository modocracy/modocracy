@echo off
rem Builds two single-file executables: standard and diagnostic.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [0/3] Creating .venv...
  python -m venv .venv || goto :fail
)
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%~dp0build\tmp" mkdir "%~dp0build\tmp"
set "TEMP=%~dp0build\tmp"
set "TMP=%~dp0build\tmp"
set "PIP_CACHE_DIR=%~dp0build\pip-cache"

echo [1/3] Installing build requirements...
"%PY%" -m pip install --quiet --disable-pip-version-check -r requirements-build.txt || goto :fail

echo [2/3] Running tests...
"%PY%" -m unittest discover -s tests -t . || goto :fail

echo [3/3] Building standard and diagnostic executables...
"%PY%" "%~dp0tools\build.py" || goto :fail

echo.
echo Done: %~dp0dist\Modocracy.exe
echo Done: %~dp0dist\Modocracy-diagnostic.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1
