@echo off
rem agys launcher for Windows. Add this directory to PATH, or call agys.cmd directly.
python "%~dp0agys.py" %*
if errorlevel 1 exit /b %errorlevel%
