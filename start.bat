@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo MCC Packaging Automation Middleware
echo ============================================================
echo.

:: Set the script directory as working directory
cd /d "%~dp0"

:: Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Creating one...
    echo.

    :: Try to find Python
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=py
    ) else (
        where python >nul 2>&1
        if %errorlevel% equ 0 (
            set PYTHON_CMD=python
        ) else (
            echo ERROR: Python not found. Please install Python 3.10+ and try again.
            pause
            exit /b 1
        )
    )

    echo Using: !PYTHON_CMD!
    echo Creating virtual environment...
    !PYTHON_CMD! -m venv venv

    if not exist "venv\Scripts\activate.bat" (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )

    echo Virtual environment created successfully.
    echo.
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Check if flask is installed (as proxy for all deps)
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
    echo.
    echo Dependencies installed.
    echo.
)

:: Create necessary directories
if not exist "outputs\xml" mkdir "outputs\xml"
if not exist "outputs\logs" mkdir "outputs\logs"
if not exist "config" mkdir "config"

echo.
echo ============================================================
echo Starting server at http://localhost:5000
echo Press Ctrl+C to stop the server
echo ============================================================
echo.

:: Run the application
python run.py

:: Deactivate on exit
deactivate
