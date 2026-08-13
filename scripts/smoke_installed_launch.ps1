param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,

    [int]$TimeoutSeconds = 30,

    [switch]$KeepRunning,

    [string]$PidFile
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
$launchSucceeded = $false

function Start-WorkTraceForSmoke {
    $env:LOCALAPPDATA = $smokeRoot
    try {
        return Start-Process -FilePath $exe -PassThru
    }
    finally {
        $env:LOCALAPPDATA = $originalLocalAppData
    }
}

function Wait-ForWorkTraceWindow {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$TargetProcess
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $TargetProcess.Refresh()
        if ($TargetProcess.HasExited) {
            throw "Installed WorkTrace exited during startup with code $($TargetProcess.ExitCode)."
        }

        if (Test-Path -LiteralPath $appLog) {
            $windowLoaded = [bool](Select-String `
                -LiteralPath $appLog `
                -SimpleMatch "desktop shell window loaded" `
                -Quiet `
                -ErrorAction SilentlyContinue)
            if ($windowLoaded) {
                Start-Sleep -Seconds 2
                $TargetProcess.Refresh()
                if ($TargetProcess.HasExited) {
                    throw "Installed WorkTrace exited immediately after its WebView window loaded with code $($TargetProcess.ExitCode)."
                }
                return
            }
        }
        Start-Sleep -Milliseconds 500
    }

    $startupLogHint = if (Test-Path -LiteralPath $startupLog) {
        $startupLog
    }
    else {
        "not created"
    }
    throw "Installed WorkTrace did not load its WebView window within $TimeoutSeconds seconds; startup log: $startupLogHint"
}

function Invoke-MaintenanceShutdownControl {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$TargetProcess
    )

    $control = Start-Process `
        -FilePath $exe `
        -ArgumentList @("--shutdown-for-maintenance") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru

    $TargetProcess.Refresh()
    if ($control.ExitCode -ne 0) {
        $stillRunning = -not $TargetProcess.HasExited
        throw "Direct maintenance shutdown exited with code $($control.ExitCode); primary_alive=$stillRunning"
    }
    if (-not $TargetProcess.HasExited) {
        throw "Direct maintenance shutdown returned success but primary process remained alive: $($TargetProcess.Id)"
    }
    Write-Host "maintenance_shutdown_control=passed old_pid=$($TargetProcess.Id)"
}

if (Test-Path -LiteralPath $smokeRoot) {
    Remove-Item -Recurse -Force -LiteralPath $smokeRoot
}
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null

try {
    $process = Start-WorkTraceForSmoke
    Wait-ForWorkTraceWindow -TargetProcess $process

    if ($KeepRunning.IsPresent) {
        Invoke-MaintenanceShutdownControl -TargetProcess $process
        Remove-Item -Force -LiteralPath $appLog -ErrorAction SilentlyContinue
        Remove-Item -Force -LiteralPath $startupLog -ErrorAction SilentlyContinue
        $process = Start-WorkTraceForSmoke
        Wait-ForWorkTraceWindow -TargetProcess $process
    }

    if ($PidFile) {
        Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
    }
    $launchSucceeded = $true
    Write-Host "installed_launch_smoke=passed pid=$($process.Id) keep_running=$($KeepRunning.IsPresent)"
}
finally {
    $env:LOCALAPPDATA = $originalLocalAppData

    if ($null -ne $process -and (-not $KeepRunning.IsPresent -or -not $launchSucceeded)) {
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

    if ((-not $KeepRunning.IsPresent -or -not $launchSucceeded) -and (Test-Path -LiteralPath $smokeRoot)) {
        Remove-Item `
            -Recurse `
            -Force `
            -LiteralPath $smokeRoot `
            -ErrorAction SilentlyContinue
    }
}
