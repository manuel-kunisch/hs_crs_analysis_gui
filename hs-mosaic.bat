@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python -m hs_mosaic
) else (
    py -3 -m hs_mosaic
)

if errorlevel 1 (
    echo.
    echo The GUI exited with an error.
    pause
)

endlocal
