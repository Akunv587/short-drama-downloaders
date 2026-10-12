@echo off
chcp 65001 >nul
title zaizaicat
echo Starting zaizaicat...
cd /d "%~dp0"

:: Check if venv exists, if not suggest install
if not exist "venv\Scripts\python.exe" (
    echo [WARN] Virtual environment not found
    echo Run: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    echo Trying system Python...
    python main.py
) else (
    venv\Scripts\python main.py
)
pause
