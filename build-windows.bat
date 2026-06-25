@echo off
REM build-windows.bat — Build GhostTrax EXE and NSIS installer on Windows.

setlocal

cd /d "%~dp0"

if not exist ffmpeg.exe (
    echo Downloading ffmpeg for Windows...
    powershell -Command "Invoke-WebRequest -Uri https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile ffmpeg.zip"
    powershell -Command "Expand-Archive -Path ffmpeg.zip -DestinationPath . -Force"
    for /d %%D in (ffmpeg-*) do copy "%%D\bin\ffmpeg.exe" ffmpeg.exe
    del /q ffmpeg.zip
    for /d %%D in (ffmpeg-*) do rmdir /s /q "%%D"
)

pyinstaller --clean --noconfirm GhostTrax-windows.spec

if exist "C:\Program Files (x86)\NSIS\makensis.exe" (
    "C:\Program Files (x86)\NSIS\makensis.exe" installer.nsi
) else if exist "C:\Program Files\NSIS\makensis.exe" (
    "C:\Program Files\NSIS\makensis.exe" installer.nsi
) else (
    echo NSIS not found; installer not built.
)

echo Build complete.
dir dist\GhostTrax.exe
if exist GhostTrax_Setup.exe dir GhostTrax_Setup.exe
