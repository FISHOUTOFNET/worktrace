[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ExePath) {
    $ExePath = Join-Path $repoRoot "dist\WorkTrace.exe"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot "dist\WorkTrace-Setup.exe"
}

$exe = Resolve-Path -LiteralPath $ExePath
$installerScript = Resolve-Path -LiteralPath (Join-Path $scriptDir "windows_installer.py")
$target = [System.IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null

$name = [System.IO.Path]::GetFileNameWithoutExtension($target)
$distPath = Split-Path -Parent $target
$workPath = Join-Path $repoRoot "build\installer-pyinstaller"
$specPath = Join-Path $repoRoot "build\installer-pyinstaller"
$addData = "$exe;payload"

$python = (Get-Command python -ErrorAction Stop).Source
$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--console",
    "--name", $name,
    "--distpath", $distPath,
    "--workpath", $workPath,
    "--specpath", $specPath,
    "--add-data", $addData,
    $installerScript
)

# PyInstaller writes INFO/WARNING to stderr; under ErrorActionPreference "Stop"
# PowerShell wraps native stderr as NativeCommandError and falsely terminates.
# Relax the preference around the native call; $LASTEXITCODE is still checked.
$oldErrorActionPreference = $ErrorActionPreference
$pyinstallerExitCode = 0
try {
    $ErrorActionPreference = "Continue"
    & $python @pyinstallerArgs
    $pyinstallerExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldErrorActionPreference
}

if ($pyinstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $pyinstallerExitCode"
}

Get-Item -LiteralPath $target
