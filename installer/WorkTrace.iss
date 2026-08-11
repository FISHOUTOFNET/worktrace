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
const
  WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2BootstrapperUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  WebView2BootstrapperName = 'MicrosoftEdgeWebview2Setup.exe';

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

function WebView2VersionIsPresent(RootKey: Integer; const Subkey: String): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(RootKey, Subkey, 'pv', Version) and
    (Trim(Version) <> '') and
    (CompareText(Trim(Version), '0.0.0.0') <> 0);
end;

function IsWebView2RuntimeInstalled: Boolean;
var
  Subkey: String;
begin
  Subkey := 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid;
  Result :=
    WebView2VersionIsPresent(HKCU, Subkey) or
    WebView2VersionIsPresent(HKLM32, Subkey);
  if (not Result) and IsWin64 then
    Result := WebView2VersionIsPresent(HKLM64, Subkey);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BootstrapperPath: String;
  ResultCode: Integer;
begin
  Result := '';
  if IsWebView2RuntimeInstalled then
  begin
    Log('WebView2 Runtime prerequisite already satisfied.');
    exit;
  end;

  Log('WebView2 Runtime missing; downloading Microsoft Evergreen Bootstrapper.');
  try
    WizardForm.StatusLabel.Caption := '正在安装 Microsoft Edge WebView2 Runtime...';
    DownloadTemporaryFile(
      WebView2BootstrapperUrl,
      WebView2BootstrapperName,
      '',
      nil
    );
    BootstrapperPath := ExpandConstant('{tmp}\') + WebView2BootstrapperName;
    if not Exec(
      BootstrapperPath,
      '/silent /install',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) then
    begin
      Result :=
        'WorkTrace 需要 Microsoft Edge WebView2 Runtime，但安装器无法启动其官方安装程序。' + #13#10 +
        '请检查当前用户权限后重试。';
      exit;
    end;

    if not IsWebView2RuntimeInstalled then
    begin
      Result :=
        'WorkTrace 需要 Microsoft Edge WebView2 Runtime，但自动安装未完成（退出代码 ' +
        IntToStr(ResultCode) + '）。' + #13#10 +
        '请检查网络或组织策略，安装 Microsoft Edge WebView2 Runtime 后重新运行 WorkTrace 安装程序。';
      exit;
    end;
    Log('WebView2 Runtime prerequisite installed successfully.');
  except
    Result :=
      'WorkTrace 需要 Microsoft Edge WebView2 Runtime，但自动安装失败。' + #13#10 +
      '请检查网络或组织策略后重试。' + #13#10 +
      GetExceptionMessage;
  end;
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
