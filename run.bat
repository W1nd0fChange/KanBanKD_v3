@echo off
cd /d "%~dp0"
REM Старый python с прошлой папки мог остаться на порту 8765.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
if exist __pycache__ rmdir /s /q __pycache__
python app.py