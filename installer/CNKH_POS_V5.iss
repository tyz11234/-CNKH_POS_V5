#define MyAppName "CNKH Hardware POS V5"
#define MyAppVersion "5.0.0-alpha.4"
#define MyAppPublisher "CNKH Hardware"

[Setup]
AppId={{6B842EAB-7D79-4E91-A0ED-61B4F326A4EA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\CNKH Hardware POS V5
DefaultGroupName=CNKH Hardware POS V5
OutputDir=..\release
OutputBaseFilename=CNKH_Hardware_POS_V5_Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayIcon={app}\CNKH_POS_Admin.exe
; User database stays in %LOCALAPPDATA% and is never part of install/uninstall files.

[Tasks]
Name: "desktopadmin"; Description: "Create CNKH POS Admin desktop shortcut"; GroupDescription: "Desktop shortcuts:"; Flags: unchecked
Name: "desktopstaff"; Description: "Create CNKH POS Staff desktop shortcut"; GroupDescription: "Desktop shortcuts:"; Flags: unchecked
Name: "startupstaff"; Description: "Start CNKH POS Staff after Windows sign-in"; GroupDescription: "Staff POS startup:"; Flags: unchecked

[Files]
Source: "..\dist\CNKH_POS_Admin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\CNKH_POS_Staff.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CNKH POS Admin"; Filename: "{app}\CNKH_POS_Admin.exe"
Name: "{group}\CNKH POS Staff"; Filename: "{app}\CNKH_POS_Staff.exe"
Name: "{autodesktop}\CNKH POS Admin"; Filename: "{app}\CNKH_POS_Admin.exe"; Tasks: desktopadmin
Name: "{autodesktop}\CNKH POS Staff"; Filename: "{app}\CNKH_POS_Staff.exe"; Tasks: desktopstaff
Name: "{userstartup}\CNKH POS Staff"; Filename: "{app}\CNKH_POS_Staff.exe"; Tasks: startupstaff

[Run]
Filename: "{app}\CNKH_POS_Admin.exe"; Description: "Launch CNKH POS Admin"; Flags: nowait postinstall skipifsilent
