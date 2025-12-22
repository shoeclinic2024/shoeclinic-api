@echo off
echo ========================================
echo  Shoe Clinic API v02 - Initial Setup
echo ========================================
echo.

echo [1/5] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)
echo Virtual environment created successfully!
echo.

echo [2/5] Activating virtual environment...
call .venv\Scripts\activate.bat
echo.

echo [3/5] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo Dependencies installed successfully!
echo.

echo [4/5] Initializing database migrations...
flask db init
if errorlevel 1 (
    echo Note: Migrations folder may already exist
)
flask db migrate -m "Initial v02 migration"
flask db upgrade
echo Database initialized!
echo.

echo [5/5] Setup complete!
echo.
echo ========================================
echo  Next Steps:
echo ========================================
echo 1. Update .env file with your configuration
echo 2. Run 'start_app.bat' to start the server
echo 3. Visit http://localhost:5000 in your browser
echo.
echo Press any key to exit...
pause > nul
