@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Zuerst setup-windows.ps1 ausfuehren.
  pause
  exit /b 1
)
.venv\Scripts\python.exe audio_uploader.py %*
if errorlevel 1 pause
