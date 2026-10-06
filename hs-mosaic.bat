@echo off
setlocal

cd /d "%~dp0"

rem Prefer a project virtual environment when one exists. The DirectML
rem environment created by setup_windows_directml.ps1 comes first because it
rem carries the torch-directml plugin (GPU acceleration on AMD Radeon / any
rem DirectX-12 GPU); a plain .venv is next; the system Python is the fallback.
set "PYTHON_EXE="
if exist ".venv-directml\Scripts\python.exe" set "PYTHON_EXE=.venv-directml\Scripts\python.exe"
if not defined PYTHON_EXE if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

if defined PYTHON_EXE (
    echo Using %PYTHON_EXE%
    "%PYTHON_EXE%" -m hs_mosaic
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python -m hs_mosaic
    ) else (
        py -3 -m hs_mosaic
    )
)

if errorlevel 1 (
    echo.
    echo The GUI exited with an error.
    pause
)

endlocal
