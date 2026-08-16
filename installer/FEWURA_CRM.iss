#define MyAppName "FEWURA CRM"
#define MyAppVersion "1.3.1"
#define MyAppPublisher "FEWURA"
#define MyAppExeName "FEWURA_CRM.exe"

[Setup]
AppId={{6AB943C3-8B87-4B96-8EF2-A6E6BEB729D3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\FEWURA\CRM
DefaultGroupName=FEWURA\CRM
OutputDir=output
OutputBaseFilename=FEWURA_CRM_Setup_1.3.1
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayName=FEWURA CRM
CreateUninstallRegKey=yes
SetupLogging=yes
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[InstallDelete]
; Les donnees CRM sont dans %LOCALAPPDATA%\FEWURA\CRM et ne sont pas touchees.
; On supprime uniquement l'ancien programme pour eviter tout melange de DLL/modules Python.
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "..\dist\FEWURA_CRM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FEWURA CRM"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\FEWURA CRM"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer FEWURA CRM"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    { Ferme de force toutes les anciennes instances avant remplacement des fichiers. }
    Exec(ExpandConstant('{cmd}'), '/C taskkill /F /T /IM FEWURA_CRM.exe >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
