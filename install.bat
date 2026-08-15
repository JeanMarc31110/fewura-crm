@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python 3.11+ requis.& pause & exit /b 1)
if not exist ".venv" %PY% -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist ".env" copy ".env.example" ".env" >nul
echo Installation FEWURA CRM Agent terminee.
echo Configurez .env puis lancez start.bat.
pause
