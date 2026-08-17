@echo off
setlocal
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0install-client.ps1"
if errorlevel 1 (
    echo.
    echo Installation impossible. Vérifiez votre connexion Internet et la disponibilité de la release GitHub.
    pause
    exit /b 1
)
exit /b 0
