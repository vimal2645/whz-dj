@echo off
title Lofi & Slowed+Reverb Audio Generator
cls
echo ===================================================
echo   Starting Lofi & Slowed+Reverb Generator...
echo ===================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    echo.
    pause
    exit /b
)

:: 2. Install requirements automatically
echo [1/3] Installing/verifying dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Dependency installation had issues. Trying to proceed...
)
echo.

:: 3. Start FastAPI Backend in background
echo [2/3] Launching FastAPI Backend Engine...
start /b uvicorn main:app --host 127.0.0.1 --port 8000

:: 4. Pause briefly for backend startup
echo Waiting for server to initialize...
timeout /t 3 /nobreak >nul
echo.

:: 5. Launch Streamlit Frontend
echo [3/3] Opening Web App in your default browser...
streamlit run app.py

pause
