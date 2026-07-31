param(
    [string]$ConfigDir = "C:\data\dev-output\config",
    [string]$SourceFolder = "C:\data\signal_sqlite",
    [string]$MessagesFile = "messages.csv",
    [string]$OutputFolder = "C:\data\dev-output",
    [string]$Me = "",
    [string]$SignalExe = "",
    [string]$Targets = "",
    [string]$PythonExe = "",
    [string]$StateFile = "",
    [string]$LogFile = "",
    [ValidateSet("shortcut-first", "signal-first", "config-first")]
    [string]$ScanOrder = "shortcut-first",
    [int]$ShortcutSlots = 9,
    [int]$MaxAttachmentsPerConversation = 9999,
    [double]$AttachmentWaitSeconds = 10.0,
    [double]$DownloadActionTimeoutSeconds = 8.0,
    [switch]$InstallDeps,
    [switch]$DryRun,
    [switch]$ClearState,
    [switch]$ForceReprocess,
    [switch]$ManifestOnly
)

$ErrorActionPreference = "Stop"

if ($env:WSL_DISTRO_NAME) {
    throw "Run this script from native Windows PowerShell, not from WSL."
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$pythonCmd = $null

function Test-PythonHasUiDeps {
    param(
        [string[]]$Cmd
    )

    try {
        if ($Cmd.Count -eq 2) {
            & $Cmd[0] $Cmd[1] -c "import pywinauto, pyautogui" *> $null
        } else {
            & $Cmd[0] -c "import pywinauto, pyautogui" *> $null
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
        if (Test-PythonHasUiDeps -Cmd $candidate) {
            $pythonCmd = $candidate
            break
        }
    }

    if (-not $pythonCmd) {
        $pythonCmd = $candidates[0]
    }
}

if (-not (Test-PythonHasUiDeps -Cmd $pythonCmd)) {
    if ($InstallDeps) {
        Install-PythonDeps -Cmd $pythonCmd
    } else {
        if ($pythonCmd.Count -eq 2) {
            $exe = & $pythonCmd[0] $pythonCmd[1] -c "import sys; print(sys.executable)"
        } else {
            $exe = & $pythonCmd[0] -c "import sys; print(sys.executable)"
        }
        throw "Selected interpreter is missing pywinauto or pyautogui: $exe. Re-run with -InstallDeps or pass -PythonExe to an interpreter that has both packages installed."
    }
}

if ($ClearState) {
    $statePath = if ($StateFile) { $StateFile } else { Join-Path $OutputFolder "signal_ui_state.json" }
    if (Test-Path $statePath) {
        Remove-Item -LiteralPath $statePath -Force
        Write-Host "Removed automation state file: $statePath"
    }
}

$args = @(
    "signal_ui_automation.py",
    "-c", $ConfigDir,
    "-s", $SourceFolder,
    "-f", $MessagesFile,
    "-o", $OutputFolder,
    "--scan-order", $ScanOrder,
    "--shortcut-slots", $ShortcutSlots,
    "--max-attachments-per-conversation", $MaxAttachmentsPerConversation,
    "--attachment-wait-seconds", $AttachmentWaitSeconds,
    "--download-action-timeout-seconds", $DownloadActionTimeoutSeconds
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
if ($StateFile) {
    $args += @("--state-file", $StateFile)
}
if ($LogFile) {
    $args += @("--log-file", $LogFile)
}
if ($DryRun) {
    $args += "--dry-run"
}
if ($ForceReprocess) {
    $args += "--force-reprocess"
}
if ($ManifestOnly) {
    $args += "--manifest-only"
}

if ($pythonCmd.Count -eq 2) {
    & $pythonCmd[0] $pythonCmd[1] @args
} else {
    & $pythonCmd[0] @args
}
