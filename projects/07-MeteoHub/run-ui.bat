@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Ошибка: не найдено виртуальное окружение .venv
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo Запуск дашборда MeteoHub на http://127.0.0.1:8501
echo (Убедитесь, что API запущен в другом окне через run-api.bat)
streamlit run ui/app.py