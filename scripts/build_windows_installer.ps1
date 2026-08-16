[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$OutputPath,
    [string]$ISCCPath
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

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
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null

$brandIcon = Join-Path $repoRoot "build\brand\worktrace.ico"
& python (Join-Path $repoRoot "scripts\generate_brand_icon.py") $brandIcon
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $brandIcon)) {
    throw "Failed to generate the 有迹 Windows icon."
}

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

$name = [System.IO.Path]::GetFileNameWithoutExtension($target)
$distPath = Split-Path -Parent $target
& $ISCCPath "/Qp" "/DMyAppExe=$exe" "/DMyAppVersion=$version" "/O$distPath" "/F$name" $installerSource
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $target)) {
    throw "Installer build completed without generating $target"
}

if ($useDefaultOutput) {
    $compatTarget = Join-Path $distPath "Trace-Setup.exe"
    Copy-Item -Force -LiteralPath $target -Destination $compatTarget
}

Get-Item -LiteralPath $target