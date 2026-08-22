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
  external 'SetEventW@kernel32.dll stdcall';

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
begin
end;
