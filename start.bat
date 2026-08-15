@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Installation absente. Lancez install.bat.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python agent.py
pause
