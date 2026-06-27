@echo off
echo GIM RENDER - Windows Setup
echo =========================

echo.
echo Step 1: Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
echo OK: Python found

echo.
echo Step 2: Checking FFmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: FFmpeg not found on PATH.
    echo Install with: winget install ffmpeg
    echo Or download from: https://ffmpeg.org/download.html
    echo The app will still run but rendering requires FFmpeg.
)
echo OK: FFmpeg found

echo.
echo Step 3: Setting up virtual environment...
if not exist ".venv" (
    python -m venv .venv
    echo Created .venv
) else (
    echo .venv already exists
)

echo.
echo Step 4: Installing dependencies...
call .venv\Scripts\activate
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo =========================
echo Setup complete!
echo.
echo To run the app:
echo   call .venv\Scripts\activate
echo   python main.py --gui      (web GUI)
echo   python main.py --gui-tk   (desktop GUI)
echo =========================
pause
