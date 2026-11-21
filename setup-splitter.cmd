@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
call :check_media
if not errorlevel 1 goto :media_ready
where winget.exe >nul 2>&1 || goto :no_media
echo Installing FFmpeg and ffprobe with Windows Package Manager...
winget.exe install --id Gyan.FFmpeg --exact --scope user --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
call :check_media || goto :no_media
:media_ready
echo FFmpeg and ffprobe are ready.
if /i "%~2"=="ffmpeg" goto :success
call "%~dp0scripts\ensure-venv.cmd" ".splitter" || goto :failed
".splitter\Scripts\python.exe" -m pip install "torch==2.5.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cpu || goto :failed
".splitter\Scripts\python.exe" -m pip install "numpy<2" "demucs==4.0.1" soundfile || goto :failed
".splitter\Scripts\python.exe" -m demucs.separate --help >nul || goto :failed
echo CPU splitter is ready.
:success
if /i not "%~1"=="--batch" pause
exit /b 0

:check_media
ffmpeg.exe -version >nul 2>&1 || exit /b 1
ffprobe.exe -version >nul 2>&1 || exit /b 1
exit /b 0

:no_media
echo Install FFmpeg from https://www.gyan.dev/ffmpeg/builds/ and add its bin directory to PATH.
echo Then reopen Voice Cover Studio and retry.
:failed
echo Setup did not complete. See the error above.
if /i not "%~1"=="--batch" pause
exit /b 1
