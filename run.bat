@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if /i "%~1"=="gui"   goto gui
if /i "%~1"=="uart"  goto uart
if /i "%~1"=="test"  goto test
if /i "%~1"=="mock"  goto guimock

:menu
echo.
echo  [ Vital GUI ]
echo   1. GUI run (python main.py)
echo   4. GUI run with virtual firmware (no module needed)
echo   2. UART demo with mock device
echo   3. Run tests (pytest)
echo   0. Exit
echo.
set /p CH=Select: 
if "%CH%"=="1" goto gui
if "%CH%"=="2" goto uart
if "%CH%"=="3" goto test
if "%CH%"=="4" goto guimock
goto end

:gui
python main.py
goto done

:guimock
python main.py --mock
goto done

:uart
python tools\uart_demo.py --mock --measure --points 4
goto done

:test
python -m pytest tests -q
goto done

:done
echo.
pause
:end
