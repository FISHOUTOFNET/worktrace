#define MyAppName "有迹"
#ifndef MyAppVersion
  #define MyAppVersion "0.1"
#endif
#define MyAppPublisher "Trace"
#define MyAppExeName "Trace.exe"
#define LegacyAppExeName "WorkTrace.exe"
#define MyInstalledIconName "Trace-Icon-" + MyAppVersion + ".ico"

#ifndef MyAppExe
  #define MyAppExe "..\dist\Trace.exe"
#endif
#ifndef MyBrandIcon
  #define MyBrandIcon "..\build\brand\worktrace.ico"
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
SetupIconFile={#MyBrandIcon}
UninstallDisplayIcon={app}\{#MyInstalledIconName}
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
; Keep temporary policy material first: solid compression otherwise forces Setup
; to decompress all preceding payload before the pre-install page can open.
Source: "..\worktrace\privacy_policy_zh-CN.txt"; Flags: dontcopy noencryption
#ifdef MyAppSourceDir
; Installed releases use the PyInstaller one-dir payload so normal launches do
; not pay the one-file extraction cost. Portable releases remain single-file.
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
; Compatibility path for local/manual one-file installer builds.
Source: "{#MyAppExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
#endif
; Shortcuts reference a versioned ICO path instead of Trace.exe. Windows Shell
; caches shortcut icons aggressively; changing this source path per release
; invalidates stale desktop/Start-menu cache entries without changing AppId.
Source: "{#MyBrandIcon}"; DestDir: "{app}"; DestName: "{#MyInstalledIconName}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\{#LegacyAppExeName}"
; Clear the previous PyInstaller one-dir runtime before writing the new one so
; removed dependencies cannot survive an in-place upgrade.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\Trace-Icon-*.ico"
Type: files; Name: "{group}\WorkTrace.lnk"
Type: files; Name: "{autodesktop}\WorkTrace.lnk"

[Icons]
Name: "{group}\有迹"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyInstalledIconName}"
Name: "{autodesktop}\有迹"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyInstalledIconName}"; Tasks: desktopicon

[Registry]
; The legacy Run value is now only a short-lived installer compatibility bootstrap.
; The frozen executable migrates it to the canonical current-user logon task below.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WorkTrace"; ValueData: """{app}\Trace.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WorkTrace"; Tasks: not startup; Flags: deletevalue
Root: HKCU; Subkey: "Software\WorkTrace\InstallBootstrap"; ValueType: dword; ValueName: "EnableFDWork"; ValueData: "1"; Tasks: fdwork; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\WorkTrace\InstallBootstrap"; ValueType: none; ValueName: "EnableFDWork"; Tasks: not fdwork; Flags: deletevalue

[Run]
; Always resolve installer/bootstrap startup state before any optional visible launch.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure-launch-at-login migrate"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "启动有迹"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove both the scheduled task and any legacy Run fallback before payload deletion.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure-launch-at-login disable"; Flags: runhidden waituntilterminated

[Code]
const
  WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2BootstrapperUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  WebView2BootstrapperName = 'MicrosoftEdgeWebview2Setup.exe';
  MaintenanceShutdownEventName = 'Local\WorkTrace_UpdateShutdown_v1';
  EventModifyState = $0002;
  Synchronize = $00100000;
  GenericWrite = $40000000;
  FileShareRead = $00000001;
  FileShareWrite = $00000002;
  FileShareDelete = $00000004;
  OpenExisting = 3;
  InvalidHandleValue = 4294967295;
  MaintenanceShutdownPollMilliseconds = 100;
  MaintenanceShutdownPollAttempts = 200;
  PrivacyPolicyFileName = 'privacy_policy_zh-CN.txt';
  PrivacyNoticeVersion = '1';
  InstallBootstrapKey = 'Software\WorkTrace\InstallBootstrap';
  PrivacyNoticeValueName = 'PrivacyNoticeVersion';
  PendingPrivacyNoticeValueName = 'PendingPrivacyNoticeVersion';

var
  FDWorkTaskNotice: TNewStaticText;
  PrivacyPage: TWizardPage;
  PrivacyMemo: TNewMemo;
  PrivacyAcceptedCheck: TNewCheckBox;
  PrivacyAcceptedForInstall: Boolean;
  PrivacyPolicyLoaded: Boolean;

function OpenEvent(
  dwDesiredAccess: DWORD;
  bInheritHandle: BOOL;
  lpName: String
): THandle;
  external 'OpenEventW@kernel32.dll stdcall';

function SetEvent(hEvent: THandle): BOOL;
  external 'SetEvent@kernel32.dll stdcall';

function CreateFile(
  lpFileName: String;
  dwDesiredAccess: DWORD;
  dwShareMode: DWORD;
  lpSecurityAttributes: DWORD;
  dwCreationDisposition: DWORD;
  dwFlagsAndAttributes: DWORD;
  hTemplateFile: THandle
): THandle;
  external 'CreateFileW@kernel32.dll stdcall';

function CloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

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
  begin
    Result := CompareText(Trim(ExistingValue), PrivacyNoticeVersion) = 0;
    // Version 2 was an unpublished historical marker for the same version-1 policy.
    if (not Result) and
       (CompareText(PrivacyNoticeVersion, '1') = 0) and
       (CompareText(Trim(ExistingValue), '2') = 0) then
      Result := True;
  end;
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

function MaintenanceShutdownEventExists: Boolean;
var
  EventHandle: THandle;
begin
  EventHandle := OpenEvent(Synchronize, False, MaintenanceShutdownEventName);
  Result := EventHandle <> 0;
  if Result then
    CloseHandle(EventHandle);
end;

function SignalMaintenanceShutdownEvent: Boolean;
var
  EventHandle: THandle;
begin
  EventHandle := OpenEvent(
    EventModifyState or Synchronize,
    False,
    MaintenanceShutdownEventName
  );
  if EventHandle = 0 then
  begin
    Result := False;
    exit;
  end;

  try
    Result := SetEvent(EventHandle);
  finally
    CloseHandle(EventHandle);
  end;
end;

function ApplicationExecutableReleased(const ExePath: String): Boolean;
var
  FileHandle: THandle;
begin
  if not FileExists(ExePath) then
  begin
    Result := True;
    exit;
  end;

  // A mapped/running executable cannot be opened for write access. We do not
  // write to it; the handle is only a precise readiness probe for replacement.
  FileHandle := CreateFile(
    ExePath,
    GenericWrite,
    FileShareRead or FileShareWrite or FileShareDelete,
    0,
    OpenExisting,
    FILE_ATTRIBUTE_NORMAL,
    0
  );
  Result := FileHandle <> InvalidHandleValue;
  if Result then
    CloseHandle(FileHandle);
end;

function RequestWorkTraceShutdown(const Context: String): Boolean;
var
  ExePath: String;
  Attempt: Integer;
  EventWasPresent: Boolean;
begin
  ExePath := ExistingApplicationExePath;
  if ExePath = '' then
  begin
    Log('Application maintenance shutdown skipped for ' + Context + ': executable not present.');
    Result := True;
    exit;
  end;

  EventWasPresent := MaintenanceShutdownEventExists;
  if EventWasPresent then
  begin
    Log('Signaling application maintenance shutdown Event for ' + Context + '.');
    if not SignalMaintenanceShutdownEvent then
    begin
      Log('Failed to signal application maintenance shutdown Event for ' + Context + '.');
      Result := False;
      exit;
    end;
  end
  else if ApplicationExecutableReleased(ExePath) then
  begin
    Log('Application executable is already released for ' + Context + '.');
    Result := True;
    exit;
  end
  else
  begin
    Log(
      'Application maintenance shutdown Event not present for ' + Context +
      ', but the executable is still in use.'
    );
    Result := False;
    exit;
  end;

  for Attempt := 1 to MaintenanceShutdownPollAttempts do
  begin
    // Event disappearance proves the inner Python process has left its shutdown
    // coordinator. File write access proves Trace.exe is no longer mapped and
    // the installed payload can be replaced safely.
    if (not MaintenanceShutdownEventExists) and
       ApplicationExecutableReleased(ExePath) then
    begin
      Log('Application maintenance shutdown completed for ' + Context + '.');
      Result := True;
      exit;
    end;

    if CompareText(Context, 'upgrade') = 0 then
      WizardForm.Repaint;
    Sleep(MaintenanceShutdownPollMilliseconds);
  end;

  Log('Application maintenance shutdown timed out for ' + Context + '.');
  Result := False;
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

function JoinPolicyLines(const Lines: TArrayOfString): String;
var
  Index: Integer;
begin
  Result := '';
  for Index := 0 to GetArrayLength(Lines) - 1 do
  begin
    if Index > 0 then
      Result := Result + #13#10;
    Result := Result + Lines[Index];
  end;
end;

procedure ConfigurePrivacyPage;
var
  PolicyLines: TArrayOfString;
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

  PrivacyPolicyLoaded := False;
  try
    ExtractTemporaryFile(PrivacyPolicyFileName);
    if LoadStringsFromFile(
      ExpandConstant('{tmp}\') + PrivacyPolicyFileName,
      PolicyLines
    ) then
    begin
      PrivacyMemo.Text := JoinPolicyLines(PolicyLines);
      PrivacyPolicyLoaded := Trim(PrivacyMemo.Text) <> '';
    end;
  except
    PrivacyPolicyLoaded := False;
  end;

  if not PrivacyPolicyLoaded then
    PrivacyMemo.Text :=
      '无法加载完整《有迹隐私政策》。请退出安装并重新运行安装程序。';

  PrivacyAcceptedCheck := TNewCheckBox.Create(PrivacyPage);
  PrivacyAcceptedCheck.Parent := PrivacyPage.Surface;
  PrivacyAcceptedCheck.Left := 0;
  PrivacyAcceptedCheck.Top := PrivacyMemo.Top + PrivacyMemo.Height + ScaleY(12);
  PrivacyAcceptedCheck.Width := PrivacyPage.SurfaceWidth;
  PrivacyAcceptedCheck.Height := ScaleY(30);
  PrivacyAcceptedCheck.Caption :=
    '我已阅读并了解《有迹隐私政策》及上述数据处理方式。';
  PrivacyAcceptedCheck.Checked := False;
  PrivacyAcceptedCheck.Enabled := PrivacyPolicyLoaded;
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
  if WizardSilent then
    exit;
  if CurPageID <> PrivacyPage.ID then
    exit;

  if not PrivacyPolicyLoaded then
  begin
    MsgBox(
      '完整《有迹隐私政策》未能加载。请退出安装并重新运行安装程序。',
      mbError,
      MB_OK
    );
    Result := False;
    exit;
  end;

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

procedure StagePrivacyAcceptanceForApplication;
begin
  if not PrivacyAcceptedForInstall then
  begin
    Log('Privacy acceptance bootstrap skipped: no interactive or prior acceptance.');
    exit;
  end;

  if not RegWriteStringValue(
    HKCU,
    InstallBootstrapKey,
    PendingPrivacyNoticeValueName,
    PrivacyNoticeVersion
  ) then
  begin
    Log('Failed to queue privacy acceptance for application persistence.');
    exit;
  end;

  if not RegWriteStringValue(
    HKCU,
    InstallBootstrapKey,
    PrivacyNoticeValueName,
    PrivacyNoticeVersion
  ) then
  begin
    Log('Failed to persist installer privacy acceptance marker.');
    exit;
  end;

  Log(
    'Privacy policy version ' + PrivacyNoticeVersion +
    ' accepted; application persistence queued for next normal launch.'
  );
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BootstrapperPath: String;
  ResultCode: Integer;
begin
  Result := '';

  if ExistingApplicationExePath <> '' then
  begin
    WizardForm.PreparingLabel.Caption :=
      '正在关闭正在运行的有迹并准备安装，请稍候...';
    WizardForm.StatusLabel.Caption := '正在关闭正在运行的有迹，请稍候...';
    WizardForm.Repaint;
    if not RequestWorkTraceShutdown('upgrade') then
      Log('Continuing upgrade so Restart Manager can apply the configured fallback.');
    WizardForm.PreparingLabel.Caption := '正在准备安装，请稍候...';
    WizardForm.StatusLabel.Caption := '正在准备安装，请稍候...';
    WizardForm.Repaint;
  end;

  if IsWebView2RuntimeInstalled then
  begin
    Log('WebView2 Runtime prerequisite already satisfied.');
    exit;
  end;

  Log('WebView2 Runtime missing; downloading Microsoft Evergreen Bootstrapper.');
  try
    WizardForm.PreparingLabel.Caption :=
      '正在安装 Microsoft Edge WebView2 Runtime，请稍候...';
    WizardForm.StatusLabel.Caption := '正在安装 Microsoft Edge WebView2 Runtime...';
    WizardForm.Repaint;
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

  WizardForm.PreparingLabel.Caption := '正在准备安装，请稍候...';

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
    StagePrivacyAcceptanceForApplication;
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
    RegDeleteValue(
      HKCU,
      InstallBootstrapKey,
      PendingPrivacyNoticeValueName
    );
  end;
end;
