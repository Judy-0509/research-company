@echo off
cd /d "%~dp0"
echo Starting Research Newsletter Backend on port 8765...
pip install -r requirements.txt -q
uvicorn main:app --host 127.0.0.1 --port 8765 --reload
