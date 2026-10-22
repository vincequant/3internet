@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\bridge;%PYTHONPATH%
if exist "bridge\python\python.exe" (
  "bridge\python\python.exe" -X utf8 -B bridge\sgi_war_cli.py %*
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -B bridge\sgi_war_cli.py %*
) else (
  python -X utf8 -B bridge\sgi_war_cli.py %*
)
