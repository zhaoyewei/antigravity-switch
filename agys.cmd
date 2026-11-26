@echo off
rem development launcher: run the agys package from this repo
setlocal
set "AGYS_ROOT=%~dp0"
set "PYTHONPATH=%AGYS_ROOT%src;%PYTHONPATH%"
python -m agys %*
endlocal & exit /b %errorlevel%
