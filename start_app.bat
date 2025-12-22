@echo off
echo ========================================
echo  Starting Shoe Clinic API v02
echo ========================================
echo.

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Setting environment variables...
set FLASK_APP=app.py
set FLASK_ENV=development

echo.
echo Starting Flask server...
echo Server will be available at: http://localhost:5000
echo Press Ctrl+C to stop the server
echo.

python app.py
pause
