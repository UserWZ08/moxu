@echo off
call "%~dp0Run-Diagnostics.cmd" %*
exit /b %errorlevel%
