param(
    [string]$SetupPath = "dist\Trace-Setup.exe",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

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
$uninstaller = Join-Path $InstallDir "unins000.exe"
$expectedStartup = '"' + (Join-Path $InstallDir "Trace.exe") + '" --background'
$upgradePidFile = Join-Path $tempRoot "worktrace-upgrade-smoke.pid"
$uninstallPidFile = Join-Path $tempRoot "worktrace-uninstall-smoke.pid"
$upgradePid = $null
$uninstallPid = $null

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        throw "$Operation exited with code $($process.ExitCode)"
    }
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -Recurse -Force -LiteralPath $InstallDir
}
Remove-Item -Force -LiteralPath $upgradePidFile -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath $uninstallPidFile -ErrorAction SilentlyContinue
Remove-ItemProperty `
    -Path $runKey `
    -Name "WorkTrace" `
    -ErrorAction SilentlyContinue

try {
    Invoke-CheckedProcess `
        -FilePath $setup `
        -Operation "First install" `
        -Arguments @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CURRENTUSER",
            "/SP-",
            "/DIR=`"$InstallDir`"",
            "/TASKS=`"startup`""
        )

    $firstStartup = Get-ItemPropertyValue `
        -Path $runKey `
        -Name "WorkTrace" `
        -ErrorAction Stop
    if ($firstStartup -ne $expectedStartup) {
        throw "First install wrote unexpected startup value: $firstStartup"
    }

    & ".\scripts\smoke_installed_launch.ps1" `
        -InstallDir $InstallDir `
        -KeepRunning `
        -PidFile $upgradePidFile
    $upgradePid = [int](Get-Content -LiteralPath $upgradePidFile -Raw)

    Copy-Item `
        -LiteralPath (Join-Path $InstallDir "Trace.exe") `
        -Destination (Join-Path $InstallDir "WorkTrace.exe") `
        -Force
    Set-ItemProperty `
        -Path $runKey `
        -Name "WorkTrace" `
        -Value '"C:\legacy\WorkTrace.exe" --background'

    Invoke-CheckedProcess `
        -FilePath $setup `
        -Operation "Upgrade install" `
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

    $upgradedStartup = Get-ItemPropertyValue `
        -Path $runKey `
        -Name "WorkTrace" `
        -ErrorAction Stop
    if ($upgradedStartup -ne $expectedStartup) {
        throw "Upgrade did not preserve enabled startup state: $upgradedStartup"
    }

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

    Remove-ItemProperty `
        -Path $runKey `
        -Name "WorkTrace" `
        -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $upgradePidFile -ErrorAction SilentlyContinue
    Remove-Item -Force -LiteralPath $uninstallPidFile -ErrorAction SilentlyContinue

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
