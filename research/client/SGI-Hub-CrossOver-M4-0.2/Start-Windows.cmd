@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "..\.venv\Scripts\pythonw.exe" (
  start "SGI Hub" "..\.venv\Scripts\pythonw.exe" -B app\mac_main.py
) else (
  start "SGI Hub" "D:\Coding\三国志internet\.venv\Scripts\pythonw.exe" -B app\mac_main.py
)
