@echo off
chcp 65001 >nul 2>&1
title DB Setup
cd /d "%~dp0"

set PSQL="C:\Program Files\PostgreSQL\16\bin\psql"
set RESTORE="C:\Program Files\PostgreSQL\16\bin\pg_restore"
set PORT=5432
set USER=postgres
set DB=ia_chatbot

echo ============================================
echo   DB Setup
echo ============================================
echo.

echo [1/2] DB init...
%PSQL% -U %USER% -h localhost -p %PORT% -f scripts\init_db.sql
if errorlevel 1 (
    echo [ERROR] DB init failed
    pause
    exit /b 1
)
echo [OK] DB initialized
echo.

if exist "ia_chatbot_backup.dump" (
    echo [2/2] Restoring data...
    %RESTORE% -U %USER% -h localhost -p %PORT% -d %DB% --clean --if-exists ia_chatbot_backup.dump
    echo [OK] Data restored
) else (
    echo [2/2] No backup file found - skip
    echo      To restore: place ia_chatbot_backup.dump in this folder
)
echo.

echo ============================================
echo   DB Setup Done!
echo ============================================
pause
