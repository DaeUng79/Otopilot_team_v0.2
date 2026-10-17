@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Read README.MD.
  exit /b 1
)
echo Open http://127.0.0.1:5190/ after the server starts.
".venv\Scripts\python.exe" "start_service.py" %*
