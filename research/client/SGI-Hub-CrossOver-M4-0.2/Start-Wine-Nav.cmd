@echo off
setlocal
cd /d "%~dp0"
if exist "bridge\python\python.exe" (
  start "SGI Wine Nav" "bridge\python\python.exe" -X utf8 -B app\wine_nav.py
) else (
  start "SGI Wine Nav" python -X utf8 -B app\wine_nav.py
)
