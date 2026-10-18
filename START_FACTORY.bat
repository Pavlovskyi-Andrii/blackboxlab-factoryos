@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo  Blackbox Lab - FactoryOS v3
echo ============================================
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  py -3 -m venv .venv 2>nul
  if errorlevel 1 python -m venv .venv
)
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
start "" "http://127.0.0.1:8080"
".venv\Scripts\python.exe" -m uvicorn app:app --reload --host 127.0.0.1 --port 8080
pause
