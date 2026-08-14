[CmdletBinding()]
param([string]$ISCCPath)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$exePath = Join-Path $repoRoot "dist\Trace.exe"
$setupPath = Join-Path $repoRoot "dist\Trace-Setup.exe"

Push-Location $repoRoot
try {
    & python -m PyInstaller --noconfirm --clean WorkTrace.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "PyInstaller completed without generating dist\Trace.exe"
}

$installerArgs = @{ ExePath = $exePath; OutputPath = $setupPath }
if ($ISCCPath) { $installerArgs.ISCCPath = $ISCCPath }
& (Join-Path $scriptDir "build_windows_installer.ps1") @installerArgs

if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Installer build completed without generating dist\Trace-Setup.exe"
}
Get-Item -LiteralPath $exePath, $setupPath
