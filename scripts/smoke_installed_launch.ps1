param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,

    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$exe = Join-Path $InstallDir "WorkTrace.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Installed WorkTrace.exe was not found at $exe"
}

$smokeRoot = if ($env:RUNNER_TEMP) {
    Join-Path $env:RUNNER_TEMP "worktrace-installed-launch-state"
}
else {
    Join-Path ([System.IO.Path]::GetTempPath()) "worktrace-installed-launch-state"
}
$appStateRoot = Join-Path $smokeRoot "WorkTrace"
$appLog = Join-Path $appStateRoot "logs\worktrace.log"
$startupLog = Join-Path $appStateRoot "logs\startup.log"
$process = $null
$originalLocalAppData = $env:LOCALAPPDATA

if (Test-Path -LiteralPath $smokeRoot) {
    Remove-Item -Recurse -Force -LiteralPath $smokeRoot
}
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null

try {
    $env:LOCALAPPDATA = $smokeRoot
    try {
        $process = Start-Process -FilePath $exe -PassThru
    }
    finally {
        $env:LOCALAPPDATA = $originalLocalAppData
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $startupObserved = $false

    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) {
            throw "Installed WorkTrace exited during startup with code $($process.ExitCode)."
        }

        if (Test-Path -LiteralPath $appLog) {
            $startupObserved = [bool](Select-String `
                -LiteralPath $appLog `
                -SimpleMatch "webview ui startup" `
                -Quiet `
                -ErrorAction SilentlyContinue)
            if ($startupObserved) {
                break
            }
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $startupObserved) {
        $startupLogHint = if (Test-Path -LiteralPath $startupLog) {
            $startupLog
        }
        else {
            "not created"
        }
        throw "Installed WorkTrace did not reach WebView startup within $TimeoutSeconds seconds; startup log: $startupLogHint"
    }

    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) {
        throw "Installed WorkTrace exited immediately after WebView startup with code $($process.ExitCode)."
    }

    Write-Host "installed_launch_smoke=passed pid=$($process.Id)"
}
finally {
    $env:LOCALAPPDATA = $originalLocalAppData

    if ($null -ne $process) {
        try {
            $process.Refresh()
            if (-not $process.HasExited) {
                & taskkill.exe /PID $process.Id /T /F *> $null
            }
        }
        catch {
            Write-Warning "Failed to terminate installed launch smoke process: $($_.Exception.Message)"
        }
    }

    if (Test-Path -LiteralPath $smokeRoot) {
        Remove-Item `
            -Recurse `
            -Force `
            -LiteralPath $smokeRoot `
            -ErrorAction SilentlyContinue
    }
}
