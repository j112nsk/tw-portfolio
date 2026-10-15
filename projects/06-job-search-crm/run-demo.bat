@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Job Search CRM: запуск с демонстрационной базой
if not exist ".venv\Scripts\activate.bat" (
    echo Не найдено виртуальное окружение .venv
    echo Создайте его: python -m venv .venv
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set PGDATABASE=job_search_crm_demo

echo Запускаю приложение с демонстрационной базой...
echo Остановить приложение: Ctrl+C в этом окне.
echo.
python -m streamlit run app\main.py

echo.
echo Приложение остановлено.
pause