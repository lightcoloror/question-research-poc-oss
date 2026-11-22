param(
    [string]$Project = "",
    [string]$Question = "多个 AI 网页端深度研究工具如何聚合成一个可控的外部研究员流程？",
    [string]$Providers = "豆包深入研究, 通义千问研究",
    [string]$SourcePolicy = "优先官方文档、开源项目源码、产品帮助中心和可复现实测；所有网页端深度研究报告只作为候选上下文。",
    [int]$FollowupWaitSeconds = 10,
    [int]$MaxWaitSeconds = 900,
    [switch]$OpenLoginProfiles,
    [switch]$LiveAutomation,
    [switch]$PrepareOnly,
    [switch]$NoOpenBrowser,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Cli = Join-Path $PSScriptRoot "research-poc.ps1"
$ConfigPath = Join-Path $Repo "config\runtime.json"
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$HostName = if ($Config.web.host) { [string]$Config.web.host } else { "127.0.0.1" }
$Port = if ($Config.web.port) { [int]$Config.web.port } else { 8775 }
$BaseUrl = "http://${HostName}:${Port}"

if (-not $Project) {
    $Project = if ($Config.project.default_root) {
        $configuredRoot = [string]$Config.project.default_root
        if ([System.IO.Path]::IsPathRooted($configuredRoot)) { $configuredRoot } else { Join-Path $Repo $configuredRoot }
    }
    else {
        Join-Path $Repo ".research-question"
    }
}

function Invoke-ResearchCli {
    param([string[]]$ArgsForCli)
    & $Cli @ArgsForCli -Python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "research-poc.ps1 failed: $($ArgsForCli -join ' ')"
    }
}

function Test-QuestionResearchWebUi {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest "$Url/api/agent/manifest?root=$([uri]::EscapeDataString($Project))" -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -eq 200 -and $response.Content.Contains("question_research_agent_manifest.v1"))
    }
    catch {
        return $false
    }
}

Write-Host "[question-research-poc] Repo: $Repo"
Write-Host "[question-research-poc] Project: $Project"
Write-Host "[question-research-poc] Web UI: $BaseUrl"

$projectJson = Join-Path $Project "research.json"
if (-not (Test-Path -LiteralPath $projectJson)) {
    Write-Host "[1/5] Initializing research project"
    Invoke-ResearchCli @("init", $Question, "--project", $Project)
}
else {
    Write-Host "[1/5] Research project already exists"
}

Write-Host "[2/5] Writing external researcher profile template"
$ProfileConfig = Join-Path $Project "config\external-researcher-profiles.json"
Invoke-ResearchCli @("write-external-researcher-profile-template", "--project", $Project, "--output-path", $ProfileConfig)

Write-Host "[3/5] Creating Omnigent-style dry-run orchestration bundle"
$OmnigentArgs = @(
    "run-omnigent-external-research-poc",
    "--project", $Project,
    "--question", $Question,
    "--clarification-answers", "启动脚本预置：先本地澄清问题，再把同一提示词分发给多个网页端深度研究工具；追问等待 $FollowupWaitSeconds 秒后使用默认回答。",
    "--providers", $Providers,
    "--source-policy", $SourcePolicy,
    "--profile-config-path", $ProfileConfig,
    "--followup-wait-seconds", [string]$FollowupWaitSeconds,
    "--max-wait-seconds", [string]$MaxWaitSeconds
)
if ($LiveAutomation) {
    Write-Warning "LiveAutomation is enabled. Browser automation may submit prompts to authorized provider sessions."
    $OmnigentArgs += "--live"
}
Invoke-ResearchCli $OmnigentArgs

if ($OpenLoginProfiles) {
    Write-Host "[4/5] Opening provider login/profile windows"
    Invoke-ResearchCli @(
        "prepare-external-researcher-login-profiles",
        "--project", $Project,
        "--profile-config-path", $ProfileConfig,
        "--providers", $Providers,
        "--live"
    )
}
else {
    Write-Host "[4/5] Login/profile windows skipped. Add -OpenLoginProfiles when you want to prepare provider sessions."
}

if ($PrepareOnly) {
    Write-Host "[5/5] PrepareOnly set; Web UI not started."
    Write-Host "[done] Project ready: $Project"
    exit 0
}

Write-Host "[5/5] Starting Web UI"
$existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingListener) {
    if (Test-QuestionResearchWebUi $BaseUrl) {
        Write-Host "[question-research-poc] Web UI is already running at $BaseUrl"
        if (-not $NoOpenBrowser) {
            Start-Process $BaseUrl
        }
        exit 0
    }
    throw "Port $Port is already listening, but it does not look like question-research-poc. Change config/runtime.json or stop the other service."
}

$WebArgs = @("run-web", "--host", $HostName, "--port", [string]$Port)
if (-not $NoOpenBrowser) {
    $WebArgs += "--open-browser"
}

Write-Host "[question-research-poc] Press Ctrl+C in this window to stop the Web UI."
Invoke-ResearchCli $WebArgs
