@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0entrega\volver_atras.ps1" %*
echo.
pause
