@echo off
chcp 65001 >nul
title TikTok 视频下载工具

echo ========================================
echo   TikTok 视频下载工具
echo ========================================
echo.

:: 检查 Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Node.js，请先安装
    pause
    exit /b 1
)

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 崩溃自动重启循环
:restart
echo.
echo [启动] 正在启动服务...
echo [提示] 服务异常退出时会自动重启
echo ========================================

:: 启动浏览器（仅首次）
if not defined BROWSER_OPENED (
    set BROWSER_OPENED=1
    start "" http://localhost:3001
)

:: 运行服务
node tiktok-video-downloader.js

:: 记录退出时间
echo.
echo [%date% %time%] 服务已退出，3秒后自动重启...
timeout /t 3 /nobreak >nul
goto restart
