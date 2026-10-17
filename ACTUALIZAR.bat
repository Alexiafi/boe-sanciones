@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0entrega\actualizar_git.ps1" %*
echo.
pause
