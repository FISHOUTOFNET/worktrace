[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$OutputPath,
    [string]$ISCCPath
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
$installerScript = Resolve-Path -LiteralPath (Join-Path $repoRoot "installer\WorkTrace.iss")
$target = [System.IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null

$name = [System.IO.Path]::GetFileNameWithoutExtension($target)
$distPath = Split-Path -Parent $target

if (-not $ISCCPath) {
    $ISCCPath = $env:ISCC_PATH
}
if (-not $ISCCPath) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($isccCommand) {
        $ISCCPath = $isccCommand.Source
    }
}
if (-not $ISCCPath) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
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
    throw "Inno Setup compiler ISCC.exe was not found. Install the pinned Inno Setup 6 toolchain or pass -ISCCPath."
}

$iscc = Resolve-Path -LiteralPath $ISCCPath
$isccArgs = @(
    "/Qp",
    "/DMyAppExe=$exe",
    "/O$distPath",
    "/F$name",
    $installerScript
)

$oldErrorActionPreference = $ErrorActionPreference
$isccExitCode = 0
try {
    $ErrorActionPreference = "Continue"
    & $iscc @isccArgs
    $isccExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldErrorActionPreference
}

if ($isccExitCode -ne 0) {
    throw "Inno Setup compiler failed with exit code $isccExitCode"
}

Get-Item -LiteralPath $target
