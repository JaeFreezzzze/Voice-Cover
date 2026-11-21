@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.." || exit /b 1
set "py312=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%py312%" goto :venv
where winget.exe >nul 2>&1 || exit /b 1
winget.exe install --id Python.Python.3.12 --exact --scope user --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
:venv
if not exist "%py312%" exit /b 1
"%py312%" -m venv .studio
exit /b %errorlevel%
