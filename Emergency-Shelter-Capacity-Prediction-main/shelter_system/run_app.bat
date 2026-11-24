@echo off
title Emergency Shelter Capacity Prediction and Redistribution System
color 0B

echo ===============================================================================
echo   EMERGENCY SHELTER CAPACITY PREDICTION AND REDISTRIBUTION SYSTEM
echo ===============================================================================
echo.

:: Ensure we are in the directory containing app.py
cd /d "%~dp0"

:: Check if virtual environment exists
if not exist "venv\Scripts\python.exe" (
    color 0C
    echo [ERROR] Virtual environment not found in venv!
    echo Please make sure the virtual environment is installed.
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking MySQL database connectivity...
venv\Scripts\python.exe -c "from app import create_app; from extensions import db; app = create_app(); app.app_context().push(); db.engine.connect(); print('       MySQL Database connected successfully.')" 2>nul
if errorlevel 1 (
    color 0E
    echo [WARNING] Could not connect to MySQL database!
    echo           Please make sure your MySQL server is running.
    echo.
)

echo.
echo ===============================================================================
echo   APPLICATION READY
echo ===============================================================================
echo   * Web Portal URL  : http://127.0.0.1:5000/
echo   * Universal Pwd   : Password@123
echo.
echo   DEMO ACCOUNTS:
echo   - Admin           : admin@shelter.gov
echo   - Authority (EOC) : authority@shelter.gov
echo   - Responder       : responder1@shelter.gov
echo   - Shelter Manager : manager1@shelter.gov [Baner Relief Camp]
echo   - Citizen User    : citizen@example.com
echo ===============================================================================
echo.
echo [2/3] Opening default web browser in 2 seconds...
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:5000/"

echo [3/3] Starting Flask Application Server...
echo (Press CTRL+C at any time to stop the server)
echo.

venv\Scripts\python.exe app.py

echo.
echo Server stopped.
pause
