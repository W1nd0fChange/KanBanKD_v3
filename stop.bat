@echo off
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  echo Останавливаем процесс %%a на порту 8765
  taskkill /F /PID %%a
)