<#
.SYNOPSIS
    Registers (or removes) a per-user Task Scheduler task that starts Spyglass at logon.

.DESCRIPTION
    The service runs hidden in the background, so the radar collects and composes the daily brief
    even when no window is open. The task belongs to the current user only: no administrator
    rights are needed and nothing is changed for other accounts.

.PARAMETER Uninstall
    Remove the task instead of creating it.

.PARAMETER TaskName
    Name of the scheduled task (default: Spyglass).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "Spyglass"
)

$ErrorActionPreference = "Stop"

# --- Remove mode -----------------------------------------------------------------------------
# Unregistering a task that does not exist is not an error: the goal state is "no such task".
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the '$TaskName' task."
    } else {
        Write-Host "No '$TaskName' task is registered; nothing to remove."
    }
    return
}

# --- Locate the program ----------------------------------------------------------------------
# The repository root is the parent of this script's folder. The service must start there so it
# finds its .env file and the project's virtual environment.
$RepoRoot = Split-Path -Parent $PSScriptRoot

# pythonw.exe is the windowless Python launcher: unlike python.exe it opens no console window,
# which is what "hidden at logon" requires.
$PythonW = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $PythonW)) {
    throw "Could not find $PythonW. Run 'uv sync' in $RepoRoot first, then run this script again."
}

# --- Describe the task -----------------------------------------------------------------------
# What to run: the service module, started in the repository folder.
$Action = New-ScheduledTaskAction -Execute $PythonW -Argument "-m spyglass_service" `
    -WorkingDirectory $RepoRoot

# When to run: when this user signs in. A short delay lets the network and the cloud-sync
# folders come up before the first collection.
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Trigger.Delay = "PT30S"

# Run as the signed-in user, without elevation. "Interactive" means the task needs that user
# to be logged on, which is exactly when the service should run.
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive `
    -RunLevel Limited

# How it behaves:
#  - keep running on battery (a laptop must still collect),
#  - run a missed start as soon as possible,
#  - never time out (the service runs for days),
#  - never start a second copy (the port would be taken),
#  - restart after a crash up to 3 times, a minute apart,
#  - hidden from the task list's normal view.
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Hidden

# --- Register it -----------------------------------------------------------------------------
# -Force replaces an existing task with the same name, so running this twice is safe.
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Force `
    -Description "Starts the Spyglass research radar service, hidden, at logon." | Out-Null

Write-Host "Registered the '$TaskName' task. Spyglass will start at your next sign-in."
Write-Host "To start it now:   Start-ScheduledTask -TaskName $TaskName"
Write-Host "To remove it:      powershell -File scripts\install_autostart.ps1 -Uninstall"
