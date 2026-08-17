@echo off
setlocal
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0install-client-pro.ps1"
if errorlevel 1 (
    echo.
    echo Installation silencieuse impossible.
    pause
    exit /b 1
)
exit /b 0
