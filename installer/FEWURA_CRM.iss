#define MyAppName "FEWURA CRM"
#define MyAppVersion "1.4.3"
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
OutputBaseFilename=FEWURA_CRM_Setup_SMS_ONLY_1.4.3
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
; IMPORTANT : ne jamais supprimer {localappdata}\FEWURA\CRM : c'est le dossier des DONNEES CRM.
; Nettoyage du programme actuellement installe.
Type: filesandordirs; Name: "{app}\*"
; Nettoyage des anciens emplacements applicatifs utilises pendant le developpement.
Type: filesandordirs; Name: "{localappdata}\Programs\FEWURA CRM\*"
Type: filesandordirs; Name: "{localappdata}\Programs\FEWURA\CRM\*"
Type: filesandordirs; Name: "{autopf}\FEWURA CRM\*"
; Supprime tous les anciens raccourcis susceptibles de pointer vers un vieil EXE.
Type: files; Name: "{userdesktop}\FEWURA CRM.lnk"
Type: files; Name: "{commondesktop}\FEWURA CRM.lnk"
Type: files; Name: "{userprograms}\FEWURA CRM.lnk"
Type: files; Name: "{commonprograms}\FEWURA CRM.lnk"
Type: files; Name: "{userdesktop}\FEWURA_CRM.exe"
Type: files; Name: "{commondesktop}\FEWURA_CRM.exe"

[Files]
Source: "..\dist\FEWURA_CRM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FEWURA CRM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\FEWURA CRM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer FEWURA CRM"; Flags: nowait postinstall skipifsilent

[Code]
procedure StopLegacyInstances();
var
  ResultCode: Integer;
begin
  { Ferme de force toutes les instances portant le nom de l'application. }
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /T /IM FEWURA_CRM.exe >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function InitializeSetup(): Boolean;
begin
  StopLegacyInstances();
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopLegacyInstances();
end;
