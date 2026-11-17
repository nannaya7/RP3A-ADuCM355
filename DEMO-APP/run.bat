@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if /i "%~1"=="mock" goto mock
python main.py
goto end
:mock
python main.py --mock
:end
pause
