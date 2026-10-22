@echo off
setlocal
cd /d "%~dp0"
if exist "bridge\python\python.exe" (
  "bridge\python\python.exe" -X utf8 -B app\room_watch.py
) else (
  python -X utf8 -B app\room_watch.py
)
