# PowerShell Script to setup Windows Task Scheduler for Qudron Autonomous Guardian
param(
    [switch]$Uninstall
)

$TaskName = "QudronAutonomousGuardian"
$PythonPath = (Get-Command python).Source
$ScriptPath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "ops\qudron-runtime\qudron_autonomous_loop.py"

if ($Uninstall) {
    Write-Host "Unregistering $TaskName..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task unregistered successfully." -ForegroundColor Green
    exit 0
}

Write-Host "Setting up Windows Task Scheduler for Qudron Autonomous Guardian..." -ForegroundColor Cyan

$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`""
# Trigger every 15 minutes, repeating for 10 years (indefinitely)
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -Priority 7 `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Automated background loop for Qudron Agent Fleet coordination and surrogate failover" `
    -Force

Write-Host "Scheduled task $TaskName registered successfully (runs safely with Priority 7 to prevent lag)." -ForegroundColor Green
