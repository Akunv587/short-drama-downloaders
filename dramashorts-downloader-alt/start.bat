@echo off
chcp 65001 >nul
title DramaShorts Downloader-fsk
cd /d "%~dp0"

echo.
echo ============================================
echo   DramaShorts Downloader-fsk
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Please install Python 3.9+ first.
    echo         Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] ffmpeg not found in PATH. HLS download will fail.
    echo        Please install ffmpeg and add to PATH.
    echo        Download: https://ffmpeg.org/download.html
    echo.
)

:: Install dependencies
echo [1/2] Installing Python dependencies...
pip install -r requirements.txt -q
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Create downloads folder
if not exist "downloads" mkdir downloads

:: Start server and open browser
echo [2/2] Starting server...
echo.
start "" http://127.0.0.1:18888
python main.py

pause
