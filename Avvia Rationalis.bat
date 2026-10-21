@echo off
rem Avvia Rationalis senza finestra di console.
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" -m rationalis %*
