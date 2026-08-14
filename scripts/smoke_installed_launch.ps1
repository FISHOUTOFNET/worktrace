param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [int]$TimeoutSeconds = 30,
    [switch]$KeepRunning,
    [string]$PidFile
)

$ErrorActionPreference = "Stop"
$exe = Join-Path $InstallDir "Trace.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Installed Trace.exe was not found at $exe"
}

$smokeRoot = if ($env:RUNNER_TEMP) {
    Join-Path $env:RUNNER_TEMP "worktrace-installed-launch-state"
} else {
    Join-Path ([System.IO.Path]::GetTempPath()) "worktrace-installed-launch-state"
}
# Existing installations keep their legacy local state root after the rename.
$appLog = Join-Path $smokeRoot "WorkTrace\logs\worktrace.log"
$originalLocalAppData = $env:LOCALAPPDATA
$process = $null
$launchSucceeded = $false

try {
    $env:LOCALAPPDATA = $smokeRoot
    $process = Start-Process -FilePath $exe -PassThru
    $env:LOCALAPPDATA = $originalLocalAppData

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) {
            throw "Installed Trace exited during startup with code $($process.ExitCode)."
        }
        if ((Test-Path -LiteralPath $appLog) -and
            (Select-String -LiteralPath $appLog -SimpleMatch "desktop shell window loaded" -Quiet -ErrorAction SilentlyContinue)) {
            $launchSucceeded = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $launchSucceeded) {
        throw "Installed Trace did not load its WebView window within $TimeoutSeconds seconds."
    }

    if ($PidFile) {
        Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
    }
    Write-Host "installed_launch_smoke=passed pid=$($process.Id) keep_running=$($KeepRunning.IsPresent)"
}
finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    if ($null -ne $process -and -not $KeepRunning.IsPresent) {
        $process.Refresh()
        if (-not $process.HasExited) {
            $process.Kill()
            $process.WaitForExit(5000) | Out-Null
        }
    }
}
