; Inno Setup script for the EditReady Windows installer.
; The build service runs:  ISCC.exe /DMyAppVersion=1.0.0 packaging\windows-installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E0A-9C1E-2D5B7A9F4E31}
AppName=EditReady
AppVersion={#MyAppVersion}
AppVerName=EditReady {#MyAppVersion}
AppPublisher=EditReady contributors
DefaultDirName={autopf}\EditReady
DefaultGroupName=EditReady
DisableProgramGroupPage=yes
; Installs for the current user only, so no admin password is needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=EditReady-Setup-Windows
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\EditReady.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\EditReady\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\EditReady"; Filename: "{app}\EditReady.exe"
Name: "{autodesktop}\EditReady"; Filename: "{app}\EditReady.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\EditReady.exe"; Description: "{cm:LaunchProgram,EditReady}"; Flags: nowait postinstall skipifsilent
