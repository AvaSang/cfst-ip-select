@echo off
python "%~dp0scripts\select_ip.py" %*
set "CFST_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %CFST_EXIT%
