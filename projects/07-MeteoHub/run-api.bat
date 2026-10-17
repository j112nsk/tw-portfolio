@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Ошибка: не найдено виртуальное окружение .venv
    echo Создайте: python -m venv .venv
    echo Затем:   .venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo Запуск MeteoHub API на http://127.0.0.1:8000
echo Swagger UI: http://127.0.0.1:8000/docs
echo Ctrl+C для остановки
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload