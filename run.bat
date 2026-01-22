@echo off
set PYTHONPATH=%cd%;%cd%\temp
echo Starting CTP Penetration Test...
".venv\Scripts\python.exe" src/main.py
pause
