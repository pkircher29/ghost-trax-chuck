!include MUI2.nsh

Name "Stem Separator"
OutFile "StemSeparator_Setup.exe"
InstallDir "$LOCALAPPDATA\StemSeparator"
RequestExecutionLevel user

!define MUI_ABORTWARNING
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
    File /r "dist\StemSeparator.exe"
    File "ffmpeg.exe"

    CreateShortcut "$DESKTOP\Stem Separator.lnk" "$INSTDIR\StemSeparator.exe"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StemSeparator" "DisplayName" "Stem Separator"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StemSeparator" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StemSeparator" "InstallLocation" "$INSTDIR"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\StemSeparator.exe"
    Delete "$INSTDIR\ffmpeg.exe"
    Delete "$INSTDIR\Uninstall.exe"
    Delete "$DESKTOP\Stem Separator.lnk"
    RMDir "$INSTDIR"

    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StemSeparator"
SectionEnd
