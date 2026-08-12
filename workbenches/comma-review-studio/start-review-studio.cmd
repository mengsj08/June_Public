@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 apps\review-studio\server.py --doctor --serve --open %*
  exit /b %ERRORLEVEL%
)

python apps\review-studio\server.py --doctor --serve --open %*
exit /b %ERRORLEVEL%
