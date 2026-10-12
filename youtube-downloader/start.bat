@echo off
chcp 65001 >nul
title YouTube 视频下载器

cd /d "%~dp0"

REM ============================================================
REM  环境检查
REM ============================================================
echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║       YouTube 视频下载器 - 一键启动            ║
echo   ╚══════════════════════════════════════════════╝
echo.
echo   [*] 检查运行环境...

REM --- Python ---
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [X] Python 未安装！请先安装 Python 3.x
    echo       https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo   [√] Python %%v

REM --- pip ---
where pip >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] pip 未找到，尝试使用 python -m pip
)

REM --- FFmpeg ---
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] FFmpeg 未安装！合并视频/音频需要它
    echo       下载: https://www.gyan.dev/ffmpeg/builds/
    echo       解压后将 bin 目录添加到系统 PATH
    echo.
) else (
    echo   [√] FFmpeg 已就绪
)

REM --- Deno (yt-dlp JS runtime) ---
set "DENO_PATH=%USERPROFILE%\.deno\bin\deno.exe"
if exist "%DENO_PATH%" (
    echo   [√] Deno 已就绪
    set "PATH=%USERPROFILE%\.deno\bin;%PATH%"
) else (
    echo   [!] Deno 未找到，正在安装...
    powershell -Command "irm https://deno.land/install.ps1 | iex" 2>nul
    if exist "%DENO_PATH%" (
        echo   [√] Deno 安装完成
        set "PATH=%USERPROFILE%\.deno\bin;%PATH%"
    ) else (
        echo   [!] Deno 自动安装失败，部分视频可能无法下载
        echo       手动安装: irm https://deno.land/install.ps1 ^| iex
    )
)

REM ============================================================
REM  依赖安装
REM ============================================================
echo.
echo   [*] 检查 Python 依赖...

pip show flask >nul 2>&1
if %errorlevel% neq 0 (
    echo   [*] 安装 Flask...
    pip install flask -q
)

pip show yt-dlp >nul 2>&1
if %errorlevel% neq 0 (
    echo   [*] 安装 yt-dlp...
    pip install yt-dlp -q
)

echo   [√] 依赖检查完成

REM ============================================================
REM  启动
REM ============================================================
echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║                                              ║
echo   ║   浏览器打开:  http://127.0.0.1:5000          ║
echo   ║                                              ║
echo   ║   按 Ctrl+C 或关闭此窗口停止服务              ║
echo   ║                                              ║
echo   ╚══════════════════════════════════════════════╝
echo.

REM 自动打开浏览器
start "" http://127.0.0.1:5000

REM 启动 Flask
python app.py

pause
