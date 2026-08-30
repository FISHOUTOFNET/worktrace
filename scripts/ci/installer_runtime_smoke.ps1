param(
    [string]$SetupPath = "",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SetupPath)) {
    [string]$version = (& python -c 'from worktrace.version import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
        throw "Unable to resolve the versioned installer path."
    }
    $SetupPath = "dist\Trace-Setup-$version.exe"
}

$setup = (Resolve-Path -LiteralPath $SetupPath).Path
$tempRoot = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    [System.IO.Path]::GetTempPath()
}
else {
    $env:RUNNER_TEMP
}
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $tempRoot "worktrace-installer-smoke"
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$startupTaskName = "WorkTrace Launch At Login"
$uninstaller = Join-Path $InstallDir "unins000.exe"
$expectedExe = Join-Path $InstallDir "Trace.exe"
$expectedStartup = '"' + $expectedExe + '" --background'
$upgradePidFile = Join-Path $tempRoot "worktrace-upgrade-smoke.pid"
$uninstallPidFile = Join-Path $tempRoot "worktrace-uninstall-smoke.pid"
$firstInstallLog = Join-Path $tempRoot "worktrace-first-install.log"
$upgradeInstallLog = Join-Path $tempRoot "worktrace-upgrade-install.log"
$uninstallLog = Join-Path $tempRoot "worktrace-uninstall.log"
$upgradePid = $null
$uninstallPid = $null

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Operation,
        [string]$LogPath = ""
    )

    $effectiveArguments = @($Arguments)
    if (-not [string]::IsNullOrWhiteSpace($LogPath)) {
        Remove-Item -Force -LiteralPath $LogPath -ErrorAction SilentlyContinue
        $effectiveArguments += "/LOG=`"$LogPath`""
    }

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $effectiveArguments `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        if (-not [string]::IsNullOrWhiteSpace($LogPath) -and (Test-Path -LiteralPath $LogPath)) {
            Write-Host "---- $Operation installer log ----"
            Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Host $_ }
            Write-Host "---- end $Operation installer log ----"
        }
        throw "$Operation exited with code $($process.ExitCode)"
    }
}

function Remove-StartupTask {
    $task = Get-ScheduledTask -TaskName $startupTaskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $startupTaskName -Confirm:$false -ErrorAction Stop
    }
}

function Assert-NoLegacyRunValue {
    $remaining = Get-ItemPropertyValue `
        -Path $runKey `
        -Name "WorkTrace" `
        -ErrorAction SilentlyContinue
    if ($null -ne $remaining) {
        throw "Legacy HKCU Run startup value remained after scheduled-task migration: $remaining"
    }
}

function Assert-CanonicalStartupTask {
    $task = Get-ScheduledTask -TaskName $startupTaskName -ErrorAction Stop
    $actions = @($task.Actions)
    if ($actions.Count -ne 1) {
        throw "Startup task has unexpected action count: $($actions.Count)"
    }
    if ($actions[0].Execute -ne $expectedExe) {
        throw "Startup task targets unexpected executable: $($actions[0].Execute)"
    }
    if ($actions[0].Arguments -ne "--background") {
        throw "Startup task has unexpected arguments: $($actions[0].Arguments)"
    }
    if ($actions[0].WorkingDirectory -ne $InstallDir) {
        throw "Startup task has unexpected working directory: $($actions[0].WorkingDirectory)"
    }
    $triggers = @($task.Triggers)
    if ($triggers.Count -ne 1 -or $triggers[0].CimClass.CimClassName -ne "MSFT_TaskLogonTrigger") {
        throw "Startup task does not have exactly one logon trigger"
    }
    Assert-NoLegacyRunValue
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -Recurse -Force -LiteralPath $InstallDir
}
Remove-Item -Force -LiteralPath $upgradePidFile -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath $uninstallPidFile -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath $firstInstallLog -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath $upgradeInstallLog -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath $uninstallLog -ErrorAction SilentlyContinue
Remove-ItemProperty `
    -Path $runKey `
    -Name "WorkTrace" `
    -ErrorAction SilentlyContinue
Remove-StartupTask

try {
    Invoke-CheckedProcess `
        -FilePath $setup `
        -Operation "First install" `
        -LogPath $firstInstallLog `
        -Arguments @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CURRENTUSER",
            "/SP-",
            "/DIR=`"$InstallDir`"",
            "/TASKS=`"startup`""
        )

    Assert-CanonicalStartupTask

    & ".\scripts\smoke_installed_launch.ps1" `
        -InstallDir $InstallDir `
        -KeepRunning `
        -PidFile $upgradePidFile
    $upgradePid = [int](Get-Content -LiteralPath $upgradePidFile -Raw)

    # Emulate an installed pre-migration release. Upgrade must preserve the
    # user's enabled preference, create the canonical scheduled task first, and
    # only then remove the legacy Run value.
    Remove-StartupTask
    Copy-Item `
        -LiteralPath (Join-Path $InstallDir "Trace.exe") `
        -Destination (Join-Path $InstallDir "WorkTrace.exe") `
        -Force
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty `
        -Path $runKey `
        -Name "WorkTrace" `
        -Value '"C:\legacy\WorkTrace.exe" --background'

    Invoke-CheckedProcess `
        -FilePath $setup `
        -Operation "Upgrade install" `
        -LogPath $upgradeInstallLog `
        -Arguments @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/NOFORCECLOSEAPPLICATIONS",
            "/CURRENTUSER",
            "/SP-",
            "/DIR=`"$InstallDir`"",
            "/TASKS=`"startup`""
        )

    if (Get-Process -Id $upgradePid -ErrorAction SilentlyContinue) {
        throw "Upgrade left the running Trace process alive: $upgradePid"
    }
    if (Test-Path -LiteralPath (Join-Path $InstallDir "WorkTrace.exe")) {
        throw "Upgrade left legacy WorkTrace.exe behind"
    }

    Assert-CanonicalStartupTask

    if (-not (Test-Path -LiteralPath $uninstaller)) {
        throw "Installer smoke uninstaller was not generated"
    }

    & ".\scripts\smoke_installed_launch.ps1" `
        -InstallDir $InstallDir `
        -KeepRunning `
        -PidFile $uninstallPidFile
    $uninstallPid = [int](Get-Content -LiteralPath $uninstallPidFile -Raw)

    Invoke-CheckedProcess `
        -FilePath $uninstaller `
        -Operation "Uninstall" `
        -LogPath $uninstallLog `
        -Arguments @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART"
        )

    if (Get-Process -Id $uninstallPid -ErrorAction SilentlyContinue) {
        throw "Uninstall left the running Trace process alive: $uninstallPid"
    }

    $remainingStartup = (
        Get-ItemProperty `
            -Path $runKey `
            -Name "WorkTrace" `
            -ErrorAction SilentlyContinue
    ).WorkTrace
    if ($null -ne $remainingStartup) {
        throw "Uninstall left startup value behind"
    }
    if ($null -ne (Get-ScheduledTask -TaskName $startupTaskName -ErrorAction SilentlyContinue)) {
        throw "Uninstall left scheduled startup task behind"
    }
}
finally {
    foreach ($pidValue in @($upgradePid, $uninstallPid)) {
        if ($null -ne $pidValue) {
            $remaining = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                $remaining.Kill()
            }
        }
    }

    if (Test-Path -LiteralPath $uninstaller) {
        Start-Process `
            -FilePath $uninstaller `
            -ArgumentList @(
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART"
            ) `
            -WindowStyle Hidden `
            -Wait `
            -ErrorAction SilentlyContinue
    }

    Remove-StartupTask
    Remove-ItemProperty `
        -Path $runKey `
        -Name "WorkTrace" `
        -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $upgradePidFile -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $uninstallPidFile -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $firstInstallLog -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $upgradeInstallLog -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $uninstallLog -ErrorAction SilentlyContinue

    $smokeStateRoot = Join-Path $tempRoot "worktrace-installed-launch-state"
    if (Test-Path -LiteralPath $smokeStateRoot) {
        Remove-Item -Recurse -Force -LiteralPath $smokeStateRoot -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $InstallDir) {
        Remove-Item `
            -Recurse `
            -Force `
            -LiteralPath $InstallDir `
            -ErrorAction SilentlyContinue
    }
}
