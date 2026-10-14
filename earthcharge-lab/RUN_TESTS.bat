@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Спершу запустіть START.bat, щоб створити середовище й установити залежності.
    pause
    exit /b 1
)
echo Запуск автоматичних тестів: енергобаланс, закон Фарадея, одиниці, граничні значення ...
".venv\Scripts\python.exe" -m pytest
pause
endlocal
