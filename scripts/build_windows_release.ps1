[CmdletBinding()]
param(
    [string]$ISCCPath
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$buildPath = Join-Path $repoRoot "build"
$distPath = Join-Path $repoRoot "dist"
$exePath = Join-Path $distPath "WorkTrace.exe"
$setupPath = Join-Path $distPath "WorkTrace-Setup.exe"
$installerBuilder = Join-Path $scriptDir "build_windows_installer.ps1"

# A release build must never reuse an executable or installer from an earlier
# source revision. Remove only generated release artifacts; user data lives
# under LOCALAPPDATA and is never touched by this script.
if (Test-Path -LiteralPath $buildPath) {
    Remove-Item -Recurse -Force -LiteralPath $buildPath
}
foreach ($artifact in @($exePath, $setupPath)) {
    if (Test-Path -LiteralPath $artifact) {
        Remove-Item -Force -LiteralPath $artifact
    }
}
New-Item -ItemType Directory -Force -Path $distPath | Out-Null

Push-Location $repoRoot
try {
    & python -m PyInstaller --noconfirm --clean WorkTrace.spec
    $pyInstallerExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($pyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $pyInstallerExitCode"
}
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "PyInstaller completed without generating dist\WorkTrace.exe"
}

$installerArgs = @{
    ExePath = $exePath
    OutputPath = $setupPath
}
if ($ISCCPath) {
    $installerArgs.ISCCPath = $ISCCPath
}
& $installerBuilder @installerArgs

if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Installer build completed without generating dist\WorkTrace-Setup.exe"
}

Get-Item -LiteralPath $exePath, $setupPath
