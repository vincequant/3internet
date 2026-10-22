@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "SGI Quick Control" ".venv\Scripts\pythonw.exe" -B app\quick_control.py
) else if exist "..\.venv\Scripts\pythonw.exe" (
  start "SGI Quick Control" "..\.venv\Scripts\pythonw.exe" -B app\quick_control.py
) else (
  py -3 -B app\quick_control.py
  if errorlevel 1 pause
)
