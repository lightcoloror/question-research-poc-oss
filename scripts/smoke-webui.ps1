param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Project,

  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$LogDirectory
)

$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigPath = Join-Path $Repo "config\runtime.json"
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$HostName = if ($Config.web.host) { [string]$Config.web.host } else { "127.0.0.1" }
$Port = if ($Config.web.port) { [int]$Config.web.port } else { 8920 }
$BaseUrl = "http://${HostName}:${Port}"

# Save original PYTHONPATH state before overriding
$PythonPathExisted = Test-Path -Path Env:\PYTHONPATH
$OriginalPythonPath = if ($PythonPathExisted) { $env:PYTHONPATH } else { $null }

# Unique per-run log filenames within the explicit LogDirectory
$RunGuid = [guid]::NewGuid().ToString()
$Stdout = Join-Path $LogDirectory "question-research-poc-webui-smoke.$RunGuid.out.log"
$Stderr = Join-Path $LogDirectory "question-research-poc-webui-smoke.$RunGuid.err.log"

# Create the log directory at execution time if it does not yet exist
if (-not (Test-Path -LiteralPath $LogDirectory)) {
  New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
}

$Process = $null
try {
  $env:PYTHONPATH = Join-Path $Repo "src"
  $Process = Start-Process -FilePath "python" -ArgumentList @("-m", "question_research_poc.cli", "run-web") -WorkingDirectory $Repo -PassThru -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr

  $Ready = $false
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
      $probe = Invoke-WebRequest "$BaseUrl/" -UseBasicParsing -TimeoutSec 2
      if ($probe.StatusCode -eq 200) {
        $Ready = $true
        break
      }
    } catch {
      if ($Process.HasExited) {
        throw "WebUI process exited early. stdout=$(Get-Content -LiteralPath $Stdout -Raw -ErrorAction SilentlyContinue) stderr=$(Get-Content -LiteralPath $Stderr -Raw -ErrorAction SilentlyContinue)"
      }
    }
  }
  if (-not $Ready) {
    throw "WebUI did not become ready at $BaseUrl. stdout=$(Get-Content -LiteralPath $Stdout -Raw -ErrorAction SilentlyContinue) stderr=$(Get-Content -LiteralPath $Stderr -Raw -ErrorAction SilentlyContinue)"
  }
  $HomeResponse = Invoke-WebRequest "$BaseUrl/" -UseBasicParsing -TimeoutSec 5
  $ProjectApi = Invoke-WebRequest "$BaseUrl/api/project?root=$([uri]::EscapeDataString($Project))" -UseBasicParsing -TimeoutSec 5
  $Audit = Invoke-WebRequest "$BaseUrl/api/completeness-audit?root=$([uri]::EscapeDataString($Project))" -UseBasicParsing -TimeoutSec 5
  $Manifest = Invoke-WebRequest "$BaseUrl/api/agent/manifest?root=$([uri]::EscapeDataString($Project))" -UseBasicParsing -TimeoutSec 5

  [pscustomobject]@{
    ok = $true
    schema = "question_research_webui_smoke.v1"
    base_url = $BaseUrl
    runtime_config = $ConfigPath
    home_ok = ($HomeResponse.StatusCode -eq 200)
    project_api_ok = $ProjectApi.Content.Contains('"ok"')
    completeness_api_ok = $Audit.Content.Contains('question_research_completeness_audit.v1')
    manifest_api_ok = $Manifest.Content.Contains('question_research_agent_manifest.v1')
    stdout_log = $Stdout
    stderr_log = $Stderr
  } | ConvertTo-Json -Depth 4
}
finally {
  try {
    if ($Process -and -not $Process.HasExited) {
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
  }
  finally {
    if ($PythonPathExisted) {
      $env:PYTHONPATH = $OriginalPythonPath
    } else {
      Remove-Item -Path Env:\PYTHONPATH -ErrorAction SilentlyContinue
    }
  }
}
