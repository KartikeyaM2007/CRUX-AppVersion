@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Crux.ps1"
exit /b %ERRORLEVEL%
