[CmdletBinding()]
param([string]$ISCCPath)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

& python (Join-Path $scriptDir "verify_release_environment.py") --scope release
if ($LASTEXITCODE -ne 0) {
    throw "Windows release environment does not meet the minimum supported requirements."
}

[string]$version = (& python -c 'from worktrace.version import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Failed to resolve a valid 有迹 application version."
}

$exePath = Join-Path $repoRoot "dist\Trace.exe"
$portablePath = Join-Path $repoRoot "dist\Trace-$version.exe"
$setupPath = Join-Path $repoRoot "dist\Trace-Setup-$version.exe"
$compatSetupPath = Join-Path $repoRoot "dist\Trace-Setup.exe"

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
Copy-Item -Force -LiteralPath $exePath -Destination $portablePath

$installerArgs = @{ ExePath = $exePath; OutputPath = $setupPath }
if ($ISCCPath) { $installerArgs.ISCCPath = $ISCCPath }
& (Join-Path $scriptDir "build_windows_installer.ps1") @installerArgs

if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Installer build completed without generating dist\Trace-Setup-$version.exe"
}
Copy-Item -Force -LiteralPath $setupPath -Destination $compatSetupPath
if (-not (Test-Path -LiteralPath $compatSetupPath)) {
    throw "Installer build completed without generating dist\Trace-Setup.exe"
}
Get-Item -LiteralPath $portablePath, $setupPath
