@echo off
title GIM RENDER
cd /d "%~dp0"

echo =========================
echo   GIM RENDER
echo =========================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    echo Install Python 3.10+ from: https://python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo Python: %%v

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] FFmpeg not found. Attempting auto-install...
    winget install ffmpeg --accept-package-agreements --accept-source-agreements >nul 2>&1
    if %errorlevel% neq 0 (
        echo Auto-install failed. Please install manually:
        echo   winget install ffmpeg
        echo   or download from: https://ffmpeg.org/download.html
        echo.
        echo The app will start but rendering may fail without FFmpeg.
        pause
    ) else (
        echo FFmpeg installed successfully.
        echo Please restart this script.
        pause
        exit /b 0
    )
) else (
    for /f "tokens=3" %%v in ('ffmpeg -version 2^>^&1 ^| findstr "ffmpeg version"') do echo FFmpeg: %%v
)

echo.
:: Check venv
if not exist ".venv\Scripts\activate" (
    echo Virtual environment not found. Running setup...
    call setup.bat
    if %errorlevel% neq 0 (
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate

if "%1"=="web" goto web
if "%1"=="tk" goto tk
if "%1"=="cli" goto cli

:: Default: Desktop GUI
echo Starting GIM RENDER Desktop GUI...
python main.py --gui-tk
goto end

:web
echo Starting GIM RENDER Web GUI...
echo Open http://127.0.0.1:8765 in your browser
start http://127.0.0.1:8765
python main.py --gui
goto end

:tk
echo Starting GIM RENDER Desktop GUI...
python main.py --gui-tk
goto end

:cli
python main.py --help
goto end

:end
call deactivate >nul 2>&1
pause
