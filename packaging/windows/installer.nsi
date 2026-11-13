; MediathekAtlas Windows installer (NSIS). Installs per user, no administrator rights.
; Built by build_desktop.py; @VERSION@ and paths are filled in there.
Unicode true
!include "MUI2.nsh"
Name "MediathekAtlas @VERSION@"
OutFile "@OUTFILE@"
InstallDir "$LOCALAPPDATA\Programs\MediathekAtlas"
InstallDirRegKey HKCU "Software\MediathekAtlas" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "@VIVERSION@"
VIAddVersionKey "ProductName" "MediathekAtlas"
VIAddVersionKey "ProductVersion" "@VERSION@"
VIAddVersionKey "FileVersion" "@VERSION@"
VIAddVersionKey "FileDescription" "MediathekAtlas Setup"
VIAddVersionKey "LegalCopyright" "MediathekAtlas"
!define MUI_ICON "@ICON@"
!define MUI_UNICON "@ICON@"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "MediathekAtlas jetzt starten"
!define MUI_FINISHPAGE_RUN_FUNCTION StartApp
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "German"

!define LAUNCH '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\start.ps1"'

Function StartApp
  Exec '${LAUNCH}'
FunctionEnd

Section "MediathekAtlas (erforderlich)" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  ; An update replaces the program folder completely; data lives in %LOCALAPPDATA%\MediathekAtlas.
  RMDir /r "$INSTDIR\app"
  File /r "@STAGE@\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\MediathekAtlas"
  CreateShortcut "$SMPROGRAMS\MediathekAtlas\MediathekAtlas.lnk" "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\start.ps1"' "$INSTDIR\mediathekatlas.ico"
  CreateShortcut "$SMPROGRAMS\MediathekAtlas\Diagnose erstellen.lnk" "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\start.ps1" -Diagnose' "$INSTDIR\mediathekatlas.ico"
  CreateShortcut "$SMPROGRAMS\MediathekAtlas\MediathekAtlas entfernen.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\MediathekAtlas" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "DisplayName" "MediathekAtlas"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "DisplayVersion" "@VERSION@"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "Publisher" "MediathekAtlas"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "DisplayIcon" "$INSTDIR\mediathekatlas.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas" "NoRepair" 1
SectionEnd

Section "Verknüpfung auf dem Desktop" SecDesktop
  CreateShortcut "$DESKTOP\MediathekAtlas.lnk" "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\start.ps1"' "$INSTDIR\mediathekatlas.ico"
SectionEnd

Section /o "Mit Windows starten" SecAutostart
  CreateShortcut "$SMSTARTUP\MediathekAtlas.lnk" "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\start.ps1"' "$INSTDIR\mediathekatlas.ico"
SectionEnd

Section "Uninstall"
  ; Catalogue, settings and downloads stay (data folder %LOCALAPPDATA%\MediathekAtlas).
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\start.ps1"
  Delete "$INSTDIR\mediathekatlas.ico"
  Delete "$INSTDIR\LIESMICH.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  RMDir /r "$SMPROGRAMS\MediathekAtlas"
  Delete "$DESKTOP\MediathekAtlas.lnk"
  Delete "$SMSTARTUP\MediathekAtlas.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MediathekAtlas"
  DeleteRegKey HKCU "Software\MediathekAtlas"
SectionEnd
