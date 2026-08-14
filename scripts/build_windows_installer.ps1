[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$OutputPath,
    [string]$ISCCPath
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ExePath) { $ExePath = Join-Path $repoRoot "dist\Trace.exe" }
if (-not $OutputPath) { $OutputPath = Join-Path $repoRoot "dist\Trace-Setup.exe" }

$exe = Resolve-Path -LiteralPath $ExePath
$installerScript = Resolve-Path -LiteralPath (Join-Path $repoRoot "installer\WorkTrace.iss")
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
if (-not $ISCCPath -or -not (Test-Path -LiteralPath $ISCCPath)) {
    throw "Inno Setup compiler ISCC.exe was not found. Pass -ISCCPath or set ISCC_PATH."
}

$name = [System.IO.Path]::GetFileNameWithoutExtension($target)
$distPath = Split-Path -Parent $target
& $ISCCPath "/Qp" "/DMyAppExe=$exe" "/O$distPath" "/F$name" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE"
}
Get-Item -LiteralPath $target
