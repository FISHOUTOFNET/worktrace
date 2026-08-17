[CmdletBinding()]
param([string]$ISCCPath)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

function Remove-CanonicalReleaseArtifact {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    try {
        Remove-Item -Force -LiteralPath $fullPath
        return
    } catch {
        # A historical dist\Trace.exe may still be running from a developer launch.
        # Only stop a process whose executable path exactly matches the release file
        # being retired; never terminate an installed 有迹 instance by process name.
    }

    $matchingProcesses = @()
    try {
        $matchingProcesses = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.ExecutablePath -and
                    [string]::Equals(
                        [System.IO.Path]::GetFullPath([string]$_.ExecutablePath),
                        $fullPath,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
                }
        )
    } catch {
        $matchingProcesses = @()
    }

    foreach ($process in $matchingProcesses) {
        Write-Host "Stopping stale release binary process PID $($process.ProcessId): $fullPath"
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        Start-Sleep -Milliseconds 200
        try {
            Remove-Item -Force -LiteralPath $fullPath
            return
        } catch {
            if ($attempt -eq 10) {
                throw "Unable to remove previous release artifact '$fullPath'. Close any process using that exact file or exclude the release directory from software that is locking it, then retry."
            }
        }
    }
}

& python (Join-Path $scriptDir "verify_release_environment.py") --scope release
if ($LASTEXITCODE -ne 0) {
    throw "Windows release environment does not meet the minimum supported requirements."
}

[string]$version = (& python -c 'from worktrace.version import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Failed to resolve a valid 有迹 application version."
}

$distPath = Join-Path $repoRoot "dist"
$portablePath = Join-Path $distPath "Trace-$version.exe"
$setupPath = Join-Path $distPath "Trace-Setup-$version.exe"
$brandIconPath = Join-Path $repoRoot "build\brand\worktrace.ico"
$stagingRoot = Join-Path $repoRoot "build\release-staging"
$stagingPath = Join-Path $stagingRoot ([guid]::NewGuid().ToString("N"))
$stagingDistPath = Join-Path $stagingPath "dist"
$stagingWorkPath = Join-Path $stagingPath "work"
$stagedExePath = Join-Path $stagingDistPath "Trace.exe"

New-Item -ItemType Directory -Force -Path $distPath | Out-Null

# dist/ is a publication boundary, not a PyInstaller work directory. Retire all
# known Trace/WorkTrace release outputs before publishing this version so the
# completed directory contains only the two canonical versioned artifacts.
Get-ChildItem -LiteralPath $distPath -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match '^(?:Trace|WorkTrace)(?:-Setup)?(?:-\d+\.\d+\.\d+)?\.exe$'
    } |
    ForEach-Object { Remove-CanonicalReleaseArtifact -Path $_.FullName }

New-Item -ItemType Directory -Force -Path $stagingDistPath, $stagingWorkPath | Out-Null

try {
    Push-Location $repoRoot
    try {
        & python -m PyInstaller `
            --noconfirm `
            --clean `
            --distpath $stagingDistPath `
            --workpath $stagingWorkPath `
            WorkTrace.spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $stagedExePath)) {
        throw "PyInstaller completed without generating the staged Trace.exe"
    }
    if (-not (Test-Path -LiteralPath $brandIconPath)) {
        throw "PyInstaller completed without generating the canonical 有迹 icon."
    }

    # WorkTrace.spec is the sole producer of the canonical icon assets for a
    # release build. Verify the executable before any downstream consumer uses
    # that same ICO so stale or divergent icon resources cannot be published.
    & python `
        (Join-Path $repoRoot "scripts\verify_windows_exe_icon.py") `
        --exe $stagedExePath `
        --ico $brandIconPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller generated Trace.exe without the canonical 有迹 icon."
    }

    Copy-Item -Force -LiteralPath $stagedExePath -Destination $portablePath

    $installerArgs = @{ ExePath = $stagedExePath; OutputPath = $setupPath }
    if ($ISCCPath) {
        $installerArgs.ISCCPath = $ISCCPath
    }
    & (Join-Path $scriptDir "build_windows_installer.ps1") @installerArgs

    if (-not (Test-Path -LiteralPath $setupPath)) {
        throw "Installer build completed without generating dist\Trace-Setup-$version.exe"
    }

    $expectedNames = @(
        "Trace-$version.exe",
        "Trace-Setup-$version.exe"
    )
    $publishedReleaseFiles = @(
        Get-ChildItem -LiteralPath $distPath -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match '^(?:Trace|WorkTrace)(?:-Setup)?(?:-\d+\.\d+\.\d+)?\.exe$'
            }
    )
    $publishedNames = @($publishedReleaseFiles | ForEach-Object { $_.Name })
    $missingNames = @($expectedNames | Where-Object { $_ -notin $publishedNames })
    $unexpectedNames = @($publishedNames | Where-Object { $_ -notin $expectedNames })

    if ($missingNames.Count -gt 0) {
        throw "Canonical Windows release is missing: $($missingNames -join ', ')"
    }
    if ($unexpectedNames.Count -gt 0) {
        throw "Canonical Windows release contains unexpected executable artifacts: $($unexpectedNames -join ', ')"
    }

    Get-Item -LiteralPath $portablePath, $setupPath
} finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -Recurse -Force -LiteralPath $stagingPath -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $stagingPath) {
            Write-Warning "Release staging cleanup could not remove '$stagingPath'. The published dist artifacts are unaffected."
        }
    }
}
