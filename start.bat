@echo off
chcp 65001 >nul 2>&1
title IA Server
cd /d "%~dp0"

echo ============================================
echo   IA V4 Server - http://localhost:8005
echo ============================================
echo.

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
    echo [OK] venv activated
) else if exist "C:\Users\my\ia-chatbot\venv\Scripts\activate.bat" (
    call "C:\Users\my\ia-chatbot\venv\Scripts\activate.bat"
    echo [OK] venv activated
) else (
    echo [WARN] No venv found, using system python
)

python --version
echo Starting server...
echo.
start "" "%~dp0loading.html"
python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8005

echo.
echo Server stopped.
pause
