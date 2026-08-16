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

$distPath = Join-Path $repoRoot "dist"
$exePath = Join-Path $distPath "Trace.exe"
$portablePath = Join-Path $distPath "Trace-$version.exe"
$setupPath = Join-Path $distPath "Trace-Setup-$version.exe"

# A canonical release build owns the known Windows release outputs in dist/.
# Clear old Trace/WorkTrace binaries first so stale aliases and retired branding
# cannot be mistaken for artifacts produced by this build.
if (Test-Path -LiteralPath $distPath) {
    Get-ChildItem -LiteralPath $distPath -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^(?:Trace|WorkTrace)(?:-Setup)?(?:-\d+\.\d+\.\d+)?\.exe$'
        } |
        Remove-Item -Force
}

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
Get-Item -LiteralPath $portablePath, $setupPath
