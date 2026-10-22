@echo off
setlocal
cd /d "%~dp0"
if exist "bridge\python\python.exe" (
  "bridge\python\python.exe" -X utf8 -B app\quiet_wait_launch.py
) else (
  python -X utf8 -B app\quiet_wait_launch.py
)
