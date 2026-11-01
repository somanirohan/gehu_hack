@echo off
rem Double-click to start the control room (see run.ps1 for options, e.g. run.bat -Tunnel).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
pause
