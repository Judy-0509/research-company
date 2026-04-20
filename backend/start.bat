@echo off
cd /d "%~dp0"

:: Load PORT and BACKEND_HOST from .env (defaults: 8765, 127.0.0.1)
set PORT=8765
set BACKEND_HOST=127.0.0.1
if exist .env (
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        if "%%a"=="PORT" set PORT=%%b
        if "%%a"=="BACKEND_HOST" set BACKEND_HOST=%%b
    )
)

echo Starting Research Newsletter Backend on %BACKEND_HOST%:%PORT%...
pip install -r requirements.txt -q
uvicorn main:app --host %BACKEND_HOST% --port %PORT% --workers 1
