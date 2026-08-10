#define MyAppName "WorkTrace"
#define MyAppVersion "0.1"
#define MyAppPublisher "WorkTrace"
#define MyAppExeName "WorkTrace.exe"

#ifndef MyAppExe
  #define MyAppExe "..\dist\WorkTrace.exe"
#endif

[Setup]
AppId=WorkTrace
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\WorkTrace
DefaultGroupName=WorkTrace
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=WorkTrace-Setup
SetupIconFile=..\worktrace\assets\worktrace.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UsedUserAreasWarning=no
UsePreviousTasks=no
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: startup; Description: "登录 Windows 时自动启动 WorkTrace"; GroupDescription: "启动选项："; Flags: unchecked

[Files]
Source: "{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\WorkTrace"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WorkTrace"; ValueData: """{app}\WorkTrace.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WorkTrace"; Tasks: not startup; Flags: deletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 WorkTrace"; Flags: nowait postinstall skipifsilent

[Code]
function IsUpgradeInstall: Boolean;
begin
  Result := RegKeyExists(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\WorkTrace_is1'
  );
end;

function ExistingStartupMatchesInstall: Boolean;
var
  ExistingValue: String;
  ExpectedValue: String;
begin
  Result := False;
  if not RegQueryStringValue(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Run',
    'WorkTrace',
    ExistingValue
  ) then
    exit;
  ExpectedValue := '"' + ExpandConstant('{app}\WorkTrace.exe') + '" --background';
  Result := CompareText(Trim(ExistingValue), ExpectedValue) = 0;
end;

procedure InitializeWizard;
begin
  if not IsUpgradeInstall then
    WizardSelectTasks('startup')
  else if ExistingStartupMatchesInstall then
    WizardSelectTasks('startup')
  else
    WizardSelectTasks('!startup');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'WorkTrace'
    );
end;
