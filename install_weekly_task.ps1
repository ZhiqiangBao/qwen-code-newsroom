[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$NodePath,
    [Parameter(Mandatory = $true)][string]$QwenCli,
    [Parameter(Mandatory = $true)][string]$WriterConfig
)

$ErrorActionPreference = 'Stop'

function Resolve-File([string]$Path, [string]$Name) {
    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw "$Name must be an absolute path."
    }
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer -or $item.FullName.Contains('"')) {
        throw "$Name must identify a file whose path contains no double quote."
    }
    return $item.FullName
}

if ((Get-TimeZone).Id -ne 'China Standard Time') {
    throw 'The computer time zone must be China Standard Time before registering these local-time schedules.'
}

$python = Resolve-File $PythonPath 'PythonPath'
$node = Resolve-File $NodePath 'NodePath'
$qwen = Resolve-File $QwenCli 'QwenCli'
$config = Resolve-File $WriterConfig 'WriterConfig'
$wrapper = Resolve-File (Join-Path $PSScriptRoot 'weekly_issue.ps1') 'weekly_issue.ps1'
$powershell = Resolve-File (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') 'PowerShell'

$taskPath = '\'
$names = @('MondayTimes', 'MondayTimesCollect')
$backups = @{}
foreach ($name in $names) {
    $existing = Get-ScheduledTask -TaskName $name -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.State -eq 'Running') { throw "$name is running. Wait for it to finish before updating." }
        $backups[$name] = Export-ScheduledTask -TaskName $name -TaskPath $taskPath
    }
}

# Keep the existing publishing task's account; a first installation uses the current interactive account.
$existingMain = Get-ScheduledTask -TaskName 'MondayTimes' -TaskPath $taskPath -ErrorAction SilentlyContinue
$account = if ($existingMain -and $existingMain.Principal.UserId) {
    $existingMain.Principal.UserId
} else {
    [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -PythonPath "{1}" -NodePath "{2}" -QwenCli "{3}" -WriterConfig "{4}"' -f $wrapper, $python, $node, $qwen, $config
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $PSScriptRoot
$collectAction = New-ScheduledTaskAction -Execute $powershell -Argument "$arguments -CollectOnly" -WorkingDirectory $PSScriptRoot
$clock = Get-Date
$weeklyAt = $clock.Date.AddDays((8 - [int]$clock.DayOfWeek) % 7)
if ($weeklyAt -le $clock) { $weeklyAt = $weeklyAt.AddDays(7) }
$dailyAt = $clock.Date.AddHours(20)
if ($dailyAt -le $clock) { $dailyAt = $dailyAt.AddDays(1) }
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $weeklyAt
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $dailyAt
$weeklySettings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 5)
$dailySettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 29)

$attempted = @()
try {
    $attempted += 'MondayTimes'
    Register-ScheduledTask -TaskName 'MondayTimes' -TaskPath $taskPath -Action $action -Trigger $weeklyTrigger -Settings $weeklySettings -Principal $principal -Force | Out-Null
    $attempted += 'MondayTimesCollect'
    Register-ScheduledTask -TaskName 'MondayTimesCollect' -TaskPath $taskPath -Action $collectAction -Trigger $dailyTrigger -Settings $dailySettings -Principal $principal -Force | Out-Null
} catch {
    $failure = $_
    $rollbackFailures = @()
    foreach ($name in $attempted) {
        try {
            if ($backups.ContainsKey($name)) {
                Register-ScheduledTask -TaskName $name -TaskPath $taskPath -Xml $backups[$name] -Force | Out-Null
            } else {
                $created = Get-ScheduledTask -TaskName $name -TaskPath $taskPath -ErrorAction SilentlyContinue
                if ($created) { Unregister-ScheduledTask -TaskName $name -TaskPath $taskPath -Confirm:$false }
            }
        } catch {
            $rollbackFailures += "$name`: $($_.Exception.Message)"
        }
    }
    if ($rollbackFailures.Count) {
        throw "Registration failed: $($failure.Exception.Message). Rollback also failed: $($rollbackFailures -join '; ')"
    }
    throw "Registration failed and previously attempted tasks were restored: $($failure.Exception.Message)"
}

foreach ($name in $names) {
    $task = Get-ScheduledTask -TaskName $name -TaskPath $taskPath
    [pscustomobject]@{
        Name = $task.TaskName
        Trigger = ($task.Triggers | Out-String).Trim()
        Action = "$($task.Actions[0].Execute) $($task.Actions[0].Arguments)"
        Principal = $task.Principal.UserId
        ExecutionTimeLimit = $task.Settings.ExecutionTimeLimit
        WakeToRun = $task.Settings.WakeToRun
        StartWhenAvailable = $task.Settings.StartWhenAvailable
        MultipleInstances = $task.Settings.MultipleInstances
    }
}
