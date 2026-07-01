param(
    [string]$ConfigDir = "C:\data\dev-output\config",
    [string]$SourceFolder = "C:\data\signal_sqlite",
    [string]$MessagesFile = "messages.csv",
    [string]$OutputFolder = "C:\data\dev-output",
    [string]$Me = "",
    [string]$SignalExe = "",
    [string]$Targets = "",
    [string]$PythonExe = "",
    [switch]$InstallDeps,
    [switch]$DryRun,
    [switch]$ManifestOnly
)

$ErrorActionPreference = "Stop"

if ($env:WSL_DISTRO_NAME) {
    throw "Run this script from native Windows PowerShell, not from WSL."
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$pythonCmd = $null

function Test-PythonHasPywinauto {
    param(
        [string[]]$Cmd
    )

    try {
        if ($Cmd.Count -eq 2) {
            & $Cmd[0] $Cmd[1] -c "import pywinauto" *> $null
        } else {
            & $Cmd[0] -c "import pywinauto" *> $null
        }
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Install-PythonDeps {
    param(
        [string[]]$Cmd
    )

    if ($Cmd.Count -eq 2) {
        & $Cmd[0] $Cmd[1] -m pip install pywinauto pyautogui
    } else {
        & $Cmd[0] -m pip install pywinauto pyautogui
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency install failed for selected Python interpreter."
    }
}

if ($PythonExe) {
    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found: $PythonExe"
    }
    $pythonCmd = @($PythonExe)
} else {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += ,@("python")
    }

    if ($candidates.Count -eq 0) {
        throw "No Windows Python interpreter found. Install Python 3 or enable py launcher."
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonHasPywinauto -Cmd $candidate) {
            $pythonCmd = $candidate
            break
        }
    }

    if (-not $pythonCmd) {
        $pythonCmd = $candidates[0]
    }
}

if (-not (Test-PythonHasPywinauto -Cmd $pythonCmd)) {
    if ($InstallDeps) {
        Install-PythonDeps -Cmd $pythonCmd
    } else {
        if ($pythonCmd.Count -eq 2) {
            $exe = & $pythonCmd[0] $pythonCmd[1] -c "import sys; print(sys.executable)"
        } else {
            $exe = & $pythonCmd[0] -c "import sys; print(sys.executable)"
        }
        throw "Selected interpreter is missing pywinauto: $exe. Re-run with -InstallDeps or pass -PythonExe to an interpreter that has pywinauto installed."
    }
}

$args = @(
    "signal_ui_automation.py",
    "-c", $ConfigDir,
    "-s", $SourceFolder,
    "-f", $MessagesFile,
    "-o", $OutputFolder
)

if ($Me) {
    $args += @("-m", $Me)
}
if ($SignalExe) {
    $args += @("--signal-exe", $SignalExe)
}
if ($Targets) {
    $args += @("--targets", $Targets)
}
if ($DryRun) {
    $args += "--dry-run"
}
if ($ManifestOnly) {
    $args += "--manifest-only"
}

if ($pythonCmd.Count -eq 2) {
    & $pythonCmd[0] $pythonCmd[1] @args
} else {
    & $pythonCmd[0] @args
}
