@echo off
rem Builds dist\Modocracy.exe using a project-local virtual environment (.venv).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [0/3] Creating .venv...
  python -m venv .venv || goto :fail
)
set "PY=%~dp0.venv\Scripts\python.exe"

echo [1/3] Installing build requirements...
"%PY%" -m pip install --quiet --disable-pip-version-check -r requirements-build.txt || goto :fail

echo [2/3] Running tests...
"%PY%" -m unittest discover -s tests -t . || goto :fail

echo [3/3] Building exe...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name Modocracy ^
  --icon "%~dp0assets\icon.ico" ^
  --version-file "%~dp0assets\version_info.txt" ^
  --add-data "%~dp0hd2mm\web;hd2mm\web" ^
  --add-data "%~dp0assets\icon.ico;assets" ^
  --distpath "%~dp0dist" --workpath "%~dp0build\pyinstaller" --specpath "%~dp0build" ^
  "%~dp0launcher.py" || goto :fail

echo.
echo Done: %~dp0dist\Modocracy.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1
