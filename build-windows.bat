@echo off
REM build-windows.bat — Build GhostTrax EXE and NSIS installer on Windows.

setlocal

cd /d "%~dp0"

if not exist ffmpeg.exe (
    echo Downloading ffmpeg for Windows...
    powershell -Command "Invoke-WebRequest -Uri https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile ffmpeg.zip"
    powershell -Command "Expand-Archive -Path ffmpeg.zip -DestinationPath ."
    for /d %%D in (ffmpeg-*) do copy "%%D\bin\ffmpeg.exe" ffmpeg.exe
)

python -m pip install pyinstaller demucs scipy faster-whisper

python -m PyInstaller GhostTrax-windows.spec --clean

if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" (
    "%ProgramFiles(x86)%\NSIS\makensis.exe" installer.nsi
) else (
    echo NSIS not found. Skipping installer.
)

echo Build complete.
dir dist
