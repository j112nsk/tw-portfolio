@echo off
chcp 65001 >nul
echo Запуск MeteoHub (API + UI)...
start "MeteoHub API" cmd /k "run-api.bat"
timeout /t 3 /nobreak >nul
start "MeteoHub UI" cmd /k "run-ui.bat"

echo Оба сервиса запущены в отдельных окнах.
echo API: http://127.0.0.1:8000/docs
echo UI:  http://127.0.0.1:8501
echo.
echo Это окно закроется автоматически через 3 секунды...
timeout /t 3 /nobreak >nul
exit