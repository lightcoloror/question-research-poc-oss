param(
    [ValidateSet("generic", "codex", "claude")]
    [string]$Client = "generic",
    [string]$Output = "",
    [string]$ServerName = "lecture-extract",
    [string]$Python = "python",
    [switch]$Validate
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$srcRoot = Join-Path $projectRoot "src"

function New-McpConfig {
    param(
        [string]$Name,
        [string]$PythonCommand,
        [string]$Cwd,
        [string]$PythonPath
    )

    [ordered]@{
        mcpServers = [ordered]@{
            $Name = [ordered]@{
                command = $PythonCommand
                args = @("-m", "question_research_poc.mcp_server")
                cwd = $Cwd
                env = [ordered]@{
                    PYTHONPATH = $PythonPath
                }
            }
        }
    }
}

function Test-McpServerListTools {
    param(
        [string]$PythonCommand,
        [string]$Cwd,
        [string]$PythonPath
    )

    $previousPythonPath = $env:PYTHONPATH
    $pushed = $false
    try {
        if ($previousPythonPath) {
            $env:PYTHONPATH = "$PythonPath;$previousPythonPath"
        }
        else {
            $env:PYTHONPATH = $PythonPath
        }
        Push-Location -LiteralPath $Cwd
        $pushed = $true
        $raw = & $PythonCommand -m question_research_poc.mcp_server --list-tools
        if ($LASTEXITCODE -ne 0) {
            throw "MCP tool listing failed with exit code $LASTEXITCODE"
        }
        $rawText = ($raw -join "`n").Trim()
        if (-not $rawText.StartsWith("[")) {
            throw "MCP tool listing must return a top-level JSON array"
        }
        $parsed = $rawText | ConvertFrom-Json
        $toolsList = @($parsed)
        if ($toolsList.Count -lt 1) {
            throw "MCP tool listing returned no tools"
        }
        foreach ($tool in $toolsList) {
            if (-not $tool -or -not ($tool -is [System.Management.Automation.PSCustomObject])) {
                throw "MCP tool entry must be a JSON object"
            }
            $name = $tool.name
            if (-not ($name -is [string]) -or [string]::IsNullOrWhiteSpace($name)) {
                throw "MCP tool entry must have a non-empty string name"
            }
        }
        return $toolsList.Count
    }
    finally {
        try {
            if ($pushed) {
                Pop-Location
            }
        }
        finally {
            $env:PYTHONPATH = $previousPythonPath
        }
    }
}

$config = New-McpConfig `
    -Name $ServerName `
    -PythonCommand $Python `
    -Cwd $projectRoot.Path `
    -PythonPath $srcRoot

$json = $config | ConvertTo-Json -Depth 8

if ($Validate) {
    $toolCount = Test-McpServerListTools -PythonCommand $Python -Cwd $projectRoot.Path -PythonPath $srcRoot
    Write-Host "Validated $ServerName MCP server for $Client client: $toolCount tools"
}

if ($Output) {
    $resolvedOutput = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
    $parent = Split-Path -Parent $resolvedOutput
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolvedOutput, $json, $utf8NoBom)
    Write-Host "Wrote $Client MCP config to $Output"
}
else {
    $json
}
