[CmdletBinding()]
param(
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$Date,
    [switch]$CollectOnly,
    [switch]$Check,
    [string]$PythonPath,
    [string]$NodePath,
    [string]$QwenCli,
    [string]$WriterConfig
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($CollectOnly -and $Check) {
    throw 'Use either -CollectOnly or -Check.'
}

if (-not $PythonPath) {
    $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source
}

$mode = 'candidate'
if ($CollectOnly) { $mode = 'collect' }
if ($Check) { $mode = 'check' }
$runArgs = @('-B', (Join-Path $PSScriptRoot '.qwen/tools/scheduled_run.py'), '--mode', $mode)
if ($Date) { $runArgs += @('--date', $Date) }

if (-not $CollectOnly) {
    if (-not $NodePath) {
        $NodePath = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $QwenCli) {
        $qwenShim = Get-Command qwen -ErrorAction SilentlyContinue
        if ($qwenShim -and $qwenShim.Source) {
            $qwenPackage = Join-Path (Split-Path -Parent $qwenShim.Source) '../@qwen-code/qwen-code/cli-entry.js'
            if (Test-Path -LiteralPath $qwenPackage -PathType Leaf) {
                $QwenCli = (Resolve-Path -LiteralPath $qwenPackage).ProviderPath
            }
        }
    }
    if (-not $WriterConfig) {
        $WriterConfig = $env:MONDAY_TIMES_WRITER_CONFIG
    }
    if (-not $WriterConfig) {
        $WriterConfig = Join-Path $PSScriptRoot '.qwen/tools/writer.json'
    }
    if ($NodePath) { $runArgs += @('--node', $NodePath) }
    if ($QwenCli) { $runArgs += @('--qwen-cli', $QwenCli) }
    if ($WriterConfig) { $runArgs += @('--writer-config', $WriterConfig) }
}

& $PythonPath @runArgs
exit $LASTEXITCODE
