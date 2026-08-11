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
Name: startup; Description: "登录 Windows 时自动启动 WorkTrace"; GroupDescription: "附加任务："; Flags: unchecked
Name: desktopicon; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked
Name: fdwork; Description: "启用 FD Work 插件"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\WorkTrace"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\WorkTrace"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WorkTrace"; ValueData: """{app}\WorkTrace.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WorkTrace"; Tasks: not startup; Flags: deletevalue
Root: HKCU; Subkey: "Software\WorkTrace\InstallBootstrap"; ValueType: dword; ValueName: "EnableFDWork"; ValueData: "1"; Tasks: fdwork; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\WorkTrace\InstallBootstrap"; ValueType: none; ValueName: "EnableFDWork"; Tasks: not fdwork; Flags: deletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 WorkTrace"; Flags: nowait postinstall skipifsilent

[Code]
var
  FDWorkNotice: TNewStaticText;

function IsUpgradeInstall: Boolean;
begin
  Result := RegKeyExists(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\WorkTrace_is1'
  );
end;

function ExistingStartupEnabled: Boolean;
var
  ExistingValue: String;
begin
  Result := False;
  if RegQueryStringValue(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Run',
    'WorkTrace',
    ExistingValue
  ) then
    Result := Trim(ExistingValue) <> '';
end;

procedure InitializeWizard;
begin
  if not IsUpgradeInstall then
    WizardSelectTasks('startup')
  else if ExistingStartupEnabled then
    WizardSelectTasks('startup')
  else
    WizardSelectTasks('!startup');

  WizardForm.TasksList.Height := WizardForm.TasksList.Height - ScaleY(30);
  FDWorkNotice := TNewStaticText.Create(WizardForm);
  FDWorkNotice.Parent := WizardForm.SelectTasksPage;
  FDWorkNotice.Left := WizardForm.TasksList.Left;
  FDWorkNotice.Top := WizardForm.TasksList.Top + WizardForm.TasksList.Height + ScaleY(8);
  FDWorkNotice.Caption := 'FD Work 插件仅方达律师事务所可用。';
  FDWorkNotice.Font.Color := clRed;
  FDWorkNotice.Font.Style := [fsBold];
  FDWorkNotice.AutoSize := True;
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
