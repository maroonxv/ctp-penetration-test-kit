@echo off
set PYTHONPATH=%cd%
echo Starting CTP Penetration Test Web Console...

REM Start Web Server in background
start /b .venv\Scripts\python.exe src/web/app.py

REM Wait for server to start
timeout /t 3 /nobreak >nul

REM Open Browser
echo Opening browser...
start http://127.0.0.1:5006

REM Keep window open
echo Web console is running. Close this window to stop.
pause