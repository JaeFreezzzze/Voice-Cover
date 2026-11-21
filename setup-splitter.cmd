@echo off
setlocal
cd /d "%~dp0"
where ffmpeg >nul 2>&1 || goto :ffmpeg
where ffprobe >nul 2>&1 || goto :ffmpeg
call "%~dp0scripts\ensure-venv.cmd" ".splitter" || goto :failed
".splitter\Scripts\python.exe" -m pip install "torch==2.5.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cpu || goto :failed
".splitter\Scripts\python.exe" -m pip install "numpy<2" "demucs==4.0.1" soundfile || goto :failed
".splitter\Scripts\python.exe" -m demucs.separate --help >nul || goto :failed
echo CPU splitter is ready.
pause
exit /b 0
:ffmpeg
echo Install FFmpeg with ffprobe on PATH, then run this file again.
:failed
echo Setup did not complete. See the error above.
pause
exit /b 1
