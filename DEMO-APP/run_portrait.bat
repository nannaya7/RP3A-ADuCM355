@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "" pythonw main.py --profile portrait
