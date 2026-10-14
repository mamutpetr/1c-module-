@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title EARTHCHARGE LAB

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :no_python

if exist ".venv\Scripts\python.exe" goto :check_deps
echo Створюю віртуальне середовище .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :venv_failed

:check_deps
set "VPY=.venv\Scripts\python.exe"
if not exist ".venv\requirements.installed" goto :install
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 goto :install
goto :run

:install
echo Встановлюю залежності. Потрібен інтернет, це лише перший запуск і займе кілька хвилин ...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
copy /y requirements.txt ".venv\requirements.installed" >nul

:run
echo Запуск EARTHCHARGE LAB ...
"%VPY%" main.py
if errorlevel 1 (
    echo.
    echo Програма завершилася з помилкою. Текст помилки вище.
    pause
)
endlocal
exit /b 0

:no_python
echo Python не знайдено.
echo Встановіть Python 3.11 або новіший з https://www.python.org/downloads/
echo Під час встановлення позначте пункт "Add python.exe to PATH".
pause
exit /b 1

:venv_failed
echo Не вдалося створити віртуальне середовище .venv
pause
exit /b 1

:pip_failed
echo Помилка встановлення залежностей. Перевірте підключення до інтернету й запустіть START.bat ще раз.
pause
exit /b 1
