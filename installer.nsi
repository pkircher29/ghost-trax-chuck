!include MUI2.nsh

Name "GhostTrax"
OutFile "GhostTrax_Setup.exe"
InstallDir "$LOCALAPPDATA\GhostTrax"
RequestExecutionLevel user

!define MUI_ABORTWARNING
!define MUI_ICON "src\assets\icons\ghosttrax.ico"
!define MUI_UNICON "src\assets\icons\ghosttrax.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "dist\GhostTrax.exe"
    File "ffmpeg.exe"

    CreateShortcut "$DESKTOP\GhostTrax.lnk" "$INSTDIR\GhostTrax.exe" "" "$INSTDIR\GhostTrax.exe" 0

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GhostTrax" "DisplayName" "GhostTrax"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GhostTrax" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GhostTrax" "InstallLocation" "$INSTDIR"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\GhostTrax.exe"
    Delete "$INSTDIR\ffmpeg.exe"
    Delete "$INSTDIR\Uninstall.exe"
    Delete "$DESKTOP\GhostTrax.lnk"
    RMDir "$INSTDIR"

    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GhostTrax"
SectionEnd
