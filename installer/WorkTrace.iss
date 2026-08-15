#define MyAppName "有迹"
#define MyAppVersion "0.1"
#define MyAppPublisher "Trace"
#define MyAppExeName "Trace.exe"
#define LegacyAppExeName "WorkTrace.exe"

#ifndef MyAppExe
  #define MyAppExe "..\dist\Trace.exe"
#endif

[Setup]
; AppId is intentionally retained so existing WorkTrace installs upgrade in place.
AppId=WorkTrace
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Trace
DefaultGroupName=有迹
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Trace-Setup
SetupIconFile=..\build\brand\worktrace.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UsedUserAreasWarning=no
UsePreviousTasks=no
CloseApplications=force
RestartApplications=no

[Tasks]
Name: startup; Description: "登录 Windows 时自动启动有迹"; GroupDescription: "附加任务："
Name: desktopicon; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: fdwork; Description: "启用 FD Work 插件"; GroupDescription: "附加任务："

[Files]
Source: "{#MyAppExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
; Bundled only for the pre-install privacy page. The application has the same
; policy resource inside Trace.exe via the PyInstaller spec.
Source: "..\worktrace\privacy_policy_zh-CN.txt"; Flags: dontcopy

[InstallDelete]
Type: files; Name: "{app}\{#LegacyAppExeName}"
Type: files; Name: "{group}\WorkTrace.lnk"
Type: files; Name: "{autodesktop}\WorkTrace.lnk"

[Icons]
Name: "{group}\有迹"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\有迹"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Keep the legacy Run value name as a compatibility identifier; its target is Trace.exe.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WorkTrace"; ValueData: """{app}\Trace.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WorkTrace"; Tasks: not startup; Flags: deletevalue
Root: HKCU; Subkey: "Software\WorkTrace\InstallBootstrap"; ValueType: dword; ValueName: "EnableFDWork"; ValueData: "1"; Tasks: fdwork; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\WorkTrace\InstallBootstrap"; ValueType: none; ValueName: "EnableFDWork"; Tasks: not fdwork; Flags: deletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动有迹"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2BootstrapperUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  WebView2BootstrapperName = 'MicrosoftEdgeWebview2Setup.exe';
  MaintenanceShutdownArgument = '--shutdown-for-maintenance';
  PrivacyPolicyFileName = 'privacy_policy_zh-CN.txt';
  PrivacyNoticeVersion = '2';
  InstallBootstrapKey = 'Software\WorkTrace\InstallBootstrap';
  PrivacyNoticeValueName = 'PrivacyNoticeVersion';

var
  FDWorkTaskNotice: TNewStaticText;
  PrivacyPage: TWizardPage;
  PrivacyMemo: TNewMemo;
  PrivacyAcceptedCheck: TNewCheckBox;
  PrivacyAcceptedForInstall: Boolean;

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

function ExistingPrivacyVersionAccepted: Boolean;
var
  ExistingValue: String;
begin
  Result := False;
  if RegQueryStringValue(
    HKCU,
    InstallBootstrapKey,
    PrivacyNoticeValueName,
    ExistingValue
  ) then
    Result := CompareText(Trim(ExistingValue), PrivacyNoticeVersion) = 0;
end;

function ExistingApplicationExePath: String;
var
  Candidate: String;
begin
  Candidate := ExpandConstant('{app}\{#MyAppExeName}');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    exit;
  end;
  Candidate := ExpandConstant('{app}\{#LegacyAppExeName}');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    exit;
  end;
  Result := '';
end;

function RequestWorkTraceShutdown(const Context: String): Boolean;
var
  ExePath: String;
  ResultCode: Integer;
begin
  ExePath := ExistingApplicationExePath;
  if ExePath = '' then
  begin
    Log('Application maintenance shutdown skipped for ' + Context + ': executable not present.');
    Result := True;
    exit;
  end;

  Log('Requesting application maintenance shutdown for ' + Context + '.');
  if not Exec(
    ExePath,
    MaintenanceShutdownArgument,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
  begin
    Log('Failed to start maintenance shutdown client for ' + Context + '.');
    Result := False;
    exit;
  end;

  Result := ResultCode = 0;
  if Result then
    Log('Maintenance shutdown client completed for ' + Context + '.')
  else
    Log(
      'Maintenance shutdown client failed for ' + Context +
      ' with exit code ' + IntToStr(ResultCode) + '.'
    );
end;

function IsUsableWebView2Version(const Version: String): Boolean;
begin
  Result :=
    (Trim(Version) <> '') and
    (CompareText(Trim(Version), '0.0.0.0') <> 0);
end;

function IsWebView2RuntimeInstalled: Boolean;
var
  Subkey: String;
  Version: String;
begin
  Result := False;
  Subkey := 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid;

  if RegQueryStringValue(HKCU, Subkey, 'pv', Version) and
     IsUsableWebView2Version(Version) then
  begin
    Result := True;
    exit;
  end;

  if RegQueryStringValue(HKLM32, Subkey, 'pv', Version) and
     IsUsableWebView2Version(Version) then
  begin
    Result := True;
    exit;
  end;

  if IsWin64 and
     RegQueryStringValue(HKLM64, Subkey, 'pv', Version) and
     IsUsableWebView2Version(Version) then
    Result := True;
end;

procedure ConfigurePrivacyPage;
var
  PolicyText: AnsiString;
begin
  PrivacyPage := CreateCustomPage(
    wpWelcome,
    '隐私与数据',
    '安装前，请了解有迹如何处理工作数据'
  );

  PrivacyMemo := TNewMemo.Create(PrivacyPage);
  PrivacyMemo.Parent := PrivacyPage.Surface;
  PrivacyMemo.Left := 0;
  PrivacyMemo.Top := 0;
  PrivacyMemo.Width := PrivacyPage.SurfaceWidth;
  PrivacyMemo.Height := PrivacyPage.SurfaceHeight - ScaleY(54);
  PrivacyMemo.ReadOnly := True;
  PrivacyMemo.ScrollBars := ssVertical;
  PrivacyMemo.WordWrap := True;

  try
    ExtractTemporaryFile(PrivacyPolicyFileName);
    if LoadStringFromFile(
      ExpandConstant('{tmp}\') + PrivacyPolicyFileName,
      PolicyText
    ) then
      PrivacyMemo.Text := PolicyText
    else
      PrivacyMemo.Text :=
        '无法加载完整《有迹隐私政策》。请退出安装并重新运行安装程序。';
  except
    PrivacyMemo.Text :=
      '无法加载完整《有迹隐私政策》。请退出安装并重新运行安装程序。';
  end;

  PrivacyAcceptedCheck := TNewCheckBox.Create(PrivacyPage);
  PrivacyAcceptedCheck.Parent := PrivacyPage.Surface;
  PrivacyAcceptedCheck.Left := 0;
  PrivacyAcceptedCheck.Top := PrivacyMemo.Top + PrivacyMemo.Height + ScaleY(12);
  PrivacyAcceptedCheck.Width := PrivacyPage.SurfaceWidth;
  PrivacyAcceptedCheck.Height := ScaleY(30);
  PrivacyAcceptedCheck.Caption :=
    '我已阅读并了解《有迹隐私政策》及上述数据处理方式。';
  PrivacyAcceptedCheck.Checked := False;
end;

procedure ConfigureFDWorkTaskNotice;
var
  NoticeHeight: Integer;
  NoticeSpacing: Integer;
begin
  NoticeHeight := ScaleY(28);
  NoticeSpacing := ScaleY(6);

  WizardForm.TasksList.Height :=
    WizardForm.TasksList.Height - NoticeHeight - NoticeSpacing;

  FDWorkTaskNotice := TNewStaticText.Create(WizardForm);
  FDWorkTaskNotice.Parent := WizardForm.SelectTasksPage;
  FDWorkTaskNotice.Left := WizardForm.TasksList.Left;
  FDWorkTaskNotice.Top :=
    WizardForm.TasksList.Top + WizardForm.TasksList.Height + NoticeSpacing;
  FDWorkTaskNotice.Width := WizardForm.TasksList.Width;
  FDWorkTaskNotice.Height := NoticeHeight;
  FDWorkTaskNotice.AutoSize := False;
  FDWorkTaskNotice.WordWrap := True;
  FDWorkTaskNotice.Caption :=
    'FD Work 仅方达律师事务所用户可用；非方达用户请取消勾选。';
  FDWorkTaskNotice.Font.Color := clRed;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID <> PrivacyPage.ID then
    exit;

  if not PrivacyAcceptedCheck.Checked then
  begin
    MsgBox(
      '继续安装前，请阅读《有迹隐私政策》并勾选确认。',
      mbInformation,
      MB_OK
    );
    Result := False;
    exit;
  end;

  PrivacyAcceptedForInstall := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = PrivacyPage.ID) and PrivacyAcceptedForInstall;
end;

procedure PersistPrivacyAcceptanceFromInstaller;
var
  ResultCode: Integer;
  Arguments: String;
begin
  if not PrivacyAcceptedForInstall then
  begin
    Log('Privacy acceptance bootstrap skipped: no interactive or prior acceptance.');
    exit;
  end;

  Arguments :=
    '--accept-privacy-notice ' + PrivacyNoticeVersion + ' --source installer';
  if Exec(
    ExpandConstant('{app}\{#MyAppExeName}'),
    Arguments,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) and (ResultCode = 0) then
  begin
    RegWriteStringValue(
      HKCU,
      InstallBootstrapKey,
      PrivacyNoticeValueName,
      PrivacyNoticeVersion
    );
    Log('Privacy policy version ' + PrivacyNoticeVersion + ' accepted and persisted.');
  end
  else
    Log(
      'Privacy acceptance bootstrap did not complete; first-run gate remains authoritative. ' +
      'Exit code: ' + IntToStr(ResultCode)
    );
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BootstrapperPath: String;
  ResultCode: Integer;
begin
  Result := '';

  if (ExistingApplicationExePath <> '') and
     not RequestWorkTraceShutdown('upgrade') then
    Log('Continuing upgrade so Restart Manager can apply the configured fallback.');

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
        '有迹需要 Microsoft Edge WebView2 Runtime，但安装器无法启动其官方安装程序。' + #13#10 +
        '请检查当前用户权限后重试。';
      exit;
    end;

    if not IsWebView2RuntimeInstalled then
    begin
      Result :=
        '有迹需要 Microsoft Edge WebView2 Runtime，但自动安装未完成（退出代码 ' +
        IntToStr(ResultCode) + '）。' + #13#10 +
        '请检查网络或组织策略，安装 Microsoft Edge WebView2 Runtime 后重新运行有迹安装程序。';
      exit;
    end;
    Log('WebView2 Runtime prerequisite installed successfully.');
  except
    Result :=
      '有迹需要 Microsoft Edge WebView2 Runtime，但自动安装失败。' + #13#10 +
      '请检查网络或组织策略后重试。' + #13#10 +
      GetExceptionMessage;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := RequestWorkTraceShutdown('uninstall');
  if not Result then
    MsgBox(
      '有迹未能在卸载前正常退出。请从通知区域退出有迹后重试。',
      mbError,
      MB_OK
    );
end;

procedure InitializeWizard;
begin
  PrivacyAcceptedForInstall := ExistingPrivacyVersionAccepted;
  ConfigurePrivacyPage;
  ConfigureFDWorkTaskNotice;

  if not IsUpgradeInstall then
    WizardSelectTasks('startup')
  else if ExistingStartupEnabled then
    WizardSelectTasks('startup')
  else
    WizardSelectTasks('!startup');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    PersistPrivacyAcceptanceFromInstaller;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    RegDeleteValue(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'WorkTrace'
    );
    RegDeleteValue(
      HKCU,
      InstallBootstrapKey,
      PrivacyNoticeValueName
    );
  end;
end;
