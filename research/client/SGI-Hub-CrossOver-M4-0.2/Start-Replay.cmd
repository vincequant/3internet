@echo off
setlocal
cd /d "%~dp0"
if exist "bridge\python\python.exe" (
  start "SGI Replay" "bridge\python\python.exe" -X utf8 -B app\panorama_replay.py %*
) else if exist ".venv\Scripts\python.exe" (
  start "SGI Replay" ".venv\Scripts\python.exe" -X utf8 -B app\panorama_replay.py %*
) else (
  start "SGI Replay" python -X utf8 -B app\panorama_replay.py %*
)
