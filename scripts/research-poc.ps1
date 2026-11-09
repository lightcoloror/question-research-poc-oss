param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$srcRoot = Join-Path $projectRoot "src"
$previousPythonPath = $env:PYTHONPATH

try {
    if ($previousPythonPath) {
        $env:PYTHONPATH = "$srcRoot;$previousPythonPath"
    }
    else {
        $env:PYTHONPATH = $srcRoot
    }
    & $Python -m question_research_poc.cli @CliArgs
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
