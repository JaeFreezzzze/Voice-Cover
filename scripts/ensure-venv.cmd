@echo off
setlocal DisableDelayedExpansion
set "target=%~1"
if not defined target exit /b 1

if exist "%target%\Scripts\python.exe" (
    "%target%\Scripts\python.exe" -c "import sys; sys.exit(not (sys.maxsize > 2**32 and sys.version_info >= (3, 11)))" >nul 2>&1
    if not errorlevel 1 exit /b 0
    echo Existing environment "%target%" cannot start a compatible 64-bit Python.
    echo Rename this environment folder and run again to create a fresh one.
    exit /b 1
)

set "PYLAUNCHER_ALLOW_INSTALL="
for %%P in ("py -3.12" "py -3.11" "python") do (
    %%~P -c "import sys; sys.exit(not (sys.implementation.name == 'cpython' and sys.maxsize > 2**32 and sys.version_info[:2] in ((3, 12), (3, 11))))" >nul 2>&1
    if not errorlevel 1 (
        echo Creating "%target%" with %%~P
        %%~P -m venv "%target%"
        if errorlevel 1 exit /b 1
        exit /b 0
    )
)
echo Python 3.12 or 3.11 x64 was not found. Check py -0p or python --version.
exit /b 1
