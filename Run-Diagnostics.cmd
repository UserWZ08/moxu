@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0PrintDiagnostics.ps1" -NoPause
set "DiagnosticExitCode=%ERRORLEVEL%"
if not "%DiagnosticExitCode%"=="0" (
  echo.
  echo Diagnostic failed. Please send the error text shown above.
)
if /I not "%~1"=="--no-pause" pause
exit /b %DiagnosticExitCode%
