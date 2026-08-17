[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$OutputPath,
    [string]$ISCCPath
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

& python (Join-Path $repoRoot "scripts\verify_release_environment.py") --scope installer
if ($LASTEXITCODE -ne 0) {
    throw "Windows installer build environment does not meet the minimum supported requirements."
}

[string]$version = (& python -c 'from worktrace.version import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw "Failed to resolve the 有迹 application version."
}
if ($version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Invalid 有迹 application version '$version'; expected MAJOR.MINOR.PATCH."
}

if (-not $ExePath) { $ExePath = Join-Path $repoRoot "dist\Trace.exe" }
$useDefaultOutput = -not $OutputPath
if ($useDefaultOutput) {
    $OutputPath = Join-Path $repoRoot "dist\Trace-Setup-$version.exe"
}

$exe = Resolve-Path -LiteralPath $ExePath
$installerSource = Resolve-Path -LiteralPath (Join-Path $repoRoot "installer\WorkTrace.iss")
$target = [System.IO.Path]::GetFullPath($OutputPath)
$distPath = Split-Path -Parent $target
New-Item -ItemType Directory -Force -Path $distPath | Out-Null

# Never allow a previous output at the same path to make a failed compiler run
# look successful. Also retire the historical unversioned compatibility alias
# when this script is used through its canonical default-output entry point.
Remove-Item -Force -LiteralPath $target -ErrorAction SilentlyContinue
if ($useDefaultOutput) {
    Remove-Item `
        -Force `
        -LiteralPath (Join-Path $distPath "Trace-Setup.exe") `
        -ErrorAction SilentlyContinue
}

# WorkTrace.spec generates the active and paused brand assets while building
# Trace.exe. The installer is a consumer only: regenerating here can silently
# split the EXE, runtime assets, shortcuts, and Setup.exe across different ICOs.
$brandIcon = Join-Path $repoRoot "build\brand\worktrace.ico"
if (-not (Test-Path -LiteralPath $brandIcon)) {
    throw "Missing canonical 有迹 icon '$brandIcon'. Build Trace.exe with WorkTrace.spec before building the installer."
}
$brandIcon = (Resolve-Path -LiteralPath $brandIcon).Path

if (-not $ISCCPath) { $ISCCPath = $env:ISCC_PATH }
if (-not $ISCCPath) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $ISCCPath = $command.Source }
}
if (-not $ISCCPath) {
    $candidates = @()
    if (${env:ProgramFiles(x86)}) {
        $candidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
    }
    foreach ($key in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )) {
        Get-ItemProperty $key -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*Inno Setup*' -and $_.InstallLocation } |
            ForEach-Object { $candidates += (Join-Path $_.InstallLocation 'ISCC.exe') }
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            $ISCCPath = $candidate
            break
        }
    }
}
if (-not $ISCCPath -or -not (Test-Path -LiteralPath $ISCCPath)) {
    throw "Inno Setup compiler ISCC.exe was not found. Pass -ISCCPath or set ISCC_PATH."
}

$minimumInnoVersion = "6.3.0"
$minimumPreprocVersion = 100859904
$probeSource = @'
#pragma message "WORKTRACE_PREPROCVER=" + Str(PREPROCVER)
[Setup]
AppName=WorkTraceCompilerProbe
AppVersion=1
DefaultDirName={tmp}\WorkTraceCompilerProbe
'@
$probeOutput = @($probeSource | & $ISCCPath "/O-" "-" 2>&1)
$probeExitCode = $LASTEXITCODE
$probeText = $probeOutput -join "`n"
$versionMatch = [regex]::Match($probeText, 'WORKTRACE_PREPROCVER=(\d+)')
if ($probeExitCode -ne 0 -or -not $versionMatch.Success) {
    throw "Unable to determine the Inno Setup compiler version. 有迹 requires Inno Setup $minimumInnoVersion or newer. ISCC: $ISCCPath"
}
$actualPreprocVersion = [int64]$versionMatch.Groups[1].Value
if ($actualPreprocVersion -lt $minimumPreprocVersion) {
    throw "有迹 requires Inno Setup $minimumInnoVersion or newer. ISCC: $ISCCPath"
}
Write-Host "Inno Setup compiler verified: PREPROCVER=$actualPreprocVersion (minimum $minimumInnoVersion, ISCC: $ISCCPath)"

$name = [System.IO.Path]::GetFileNameWithoutExtension($target)
& $ISCCPath "/Qp" "/DMyAppExe=$exe" "/DMyAppVersion=$version" "/DMyBrandIcon=$brandIcon" "/O$distPath" "/F$name" $installerSource
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $target)) {
    throw "Installer build completed without generating $target"
}

& python `
    (Join-Path $repoRoot "scripts\verify_windows_exe_icon.py") `
    --exe $target `
    --ico $brandIcon
if ($LASTEXITCODE -ne 0) {
    throw "Installer build generated an executable without the canonical 有迹 icon."
}

Get-Item -LiteralPath $target
