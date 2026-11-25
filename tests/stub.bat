@echo off
rem test stub launcher: simulates the agy login flow
python3 -u "%~dp0login_stub.py" %*
exit /b %errorlevel%
