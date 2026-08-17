; Inno Setup installer for FEWURA CRM - pro deployment edition
[Setup]
AppName=FEWURA CRM
AppVersion=1.3.1
AppPublisher=FEWURA
AppPublisherURL=https://github.com/JeanMarc31110/fewura-crm
AppSupportURL=https://github.com/JeanMarc31110/fewura-crm/issues
AppUpdatesURL=https://github.com/JeanMarc31110/fewura-crm/releases
DefaultDirName={commonpf64}\FEWURA CRM
DefaultGroupName=FEWURA CRM
Compression=lzma
SolidCompression=yes
OutputDir=..\release
OutputBaseFilename=FEWURA_CRM_Setup
PrivilegesRequired=admin
AllowNoIcons=no
CreateAppDir=yes
UninstallDisplayIcon={app}\agent.exe
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
CreateUninstallRegKey=yes
AppendDefaultDirName=no

[Files]
Source: "..\dist\agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestName: ".env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FEWURA CRM"; Filename: "{app}\agent.exe"; WorkingDir: "{app}"
Name: "{commonprograms}\FEWURA CRM"; Filename: "{app}\agent.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\FEWURA CRM"; Filename: "{app}\agent.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\agent.exe"; Description: "Launch FEWURA CRM"; Flags: nowait postinstall skipifsilent
