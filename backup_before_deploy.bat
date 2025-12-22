@echo off
echo ========================================
echo  PRE-DEPLOYMENT BACKUP
echo  Shoe Clinic API
echo ========================================
echo.

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Creating database backup...
python scripts\pre_deployment_backup.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo  ? BACKUP FAILED!
    echo  DO NOT DEPLOY!
    echo ========================================
    pause
    exit /b 1
)

echo.
echo ========================================
echo  ? BACKUP SUCCESSFUL!
echo  Safe to deploy now.
echo ========================================
echo.
pause
