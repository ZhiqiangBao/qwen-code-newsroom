param(
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$Date,
    [switch]$CollectOnly
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not $Date) {
    $today = (Get-Date).Date
    $weekday = [int]$today.DayOfWeek
    $sinceMonday = ($weekday + 6) % 7
    $editionDay = $today.AddDays(-$sinceMonday)
    if ($CollectOnly) {
        $editionDay = $editionDay.AddDays(7)
    }
    $Date = $editionDay.ToString('yyyy-MM-dd')
}

if ($CollectOnly) {
    & python -B .qwen/tools/desk.py collect --date $Date
    exit $LASTEXITCODE
}

$prompt = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'weekly_prompt.txt')
$datedPrompt = "$Date`n$prompt"
$logs = Join-Path $PSScriptRoot 'schedule'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs "$Date.log"

$qwen = Get-Command qwen -ErrorAction Stop
$entry = $qwen.Source
$batchEntry = Join-Path (Split-Path -Parent $entry) 'qwen.cmd'
if (Test-Path -LiteralPath $batchEntry -PathType Leaf) {
    $entry = $batchEntry
}

$ErrorActionPreference = 'Continue'
& $entry -p $datedPrompt --approval-mode auto-edit --output-format json 2>&1 |
    Out-File -LiteralPath $log -Encoding UTF8
$runExit = $LASTEXITCODE
"exit=$runExit finished=$(Get-Date -Format 's')" |
    Out-File -LiteralPath $log -Append -Encoding UTF8
Write-Output $log
exit $runExit
