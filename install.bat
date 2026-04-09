@echo off
chcp 65001 >nul 2>&1
title IA Install
cd /d "%~dp0"

echo.
echo ============================================
echo   IA Install
echo ============================================
echo.

echo [1/4] Python check...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)
python --version
echo [OK]
echo.

echo [2/4] venv setup...
if not exist "%~dp0venv\Scripts\activate.bat" (
    python -m venv "%~dp0venv"
    echo [OK] venv created
) else (
    echo [OK] venv exists
)
echo.

echo [3/4] pip install...
"%~dp0venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1
"%~dp0venv\Scripts\python.exe" -m pip install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org >nul 2>&1
"%~dp0venv\Scripts\python.exe" -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)
echo [OK] packages installed
echo.

echo [4/4] Model check...
if exist "models\multilingual-e5-large\config.json" (
    echo [OK] model exists - skip
) else (
    echo Downloading model...
    python scripts\download_model.py
    if errorlevel 1 (
        echo [ERROR] model download failed
        pause
        exit /b 1
    )
    echo [OK] model downloaded
)
echo.

echo ============================================
echo   Done! Run start.bat to start server.
echo ============================================
pause
