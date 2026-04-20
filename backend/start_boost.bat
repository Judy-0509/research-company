@echo off
cd /d "%~dp0"
echo [BOOST MODE] 요약 속도 최대화 설정으로 시작합니다...
echo   - Workers: 5 (기본 3)
echo   - Batch: 100건 (기본 40)
echo   - Wall clock: 55초 (기본 180초)
echo   - API 간격: 0.5초 (기본 0.8초)
echo   - 스케줄 간격: 1분 (기본 10분)
echo.

set SUMMARIZE_WORKERS=5
set SUMMARIZE_BATCH_SIZE=100
set SUMMARIZE_WALL_CLOCK=55
set SUMMARIZE_CALL_INTERVAL=0.5
set SUMMARIZE_INTERVAL_MINUTES=1

uvicorn main:app --host 127.0.0.1 --port 8765 --workers 1
