#requires -Version 5.1
# Synthetic contract driver for the two portable PowerShell helpers.
# Hermetic by design: it builds its own fake question_research_poc package and
# never imports the real package, starts MCP, registers a client, calls a model,
# uses credentials, reaches the network or changes security/execution policy.
#
# Entry point (ordinary Windows PowerShell 5.1 only):
#   powershell.exe -NoProfile -File tests/test_qrp_wrappers_synthetic.ps1 `
#     -PythonExecutable <existing-python.exe> -OutputRoot <new-directory>
#
# -SourceRoot optionally points at a reviewed copy of the helper scripts for
# negative controls; the default is this repository checkout.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$SourceRoot = ''
)

$ErrorActionPreference = 'Stop'

# Report an honest harness result instead of a false pass if the host is wrong.
if ($PSVersionTable.PSVersion.Major -ne 5 -or [string]$PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'This synthetic driver requires ordinary Windows PowerShell 5.1 (Desktop edition).'
}

$U8 = New-Object System.Text.UTF8Encoding($false)
$PolicyPattern = 'AuthorizationManager|UnauthorizedAccess|EPERM|EACCES|Access is denied|Access denied|ExecutionPolicy|AccessDenied|SecurityException|PermissionDenied|NotAuthorized|AccessControl|Requested registry access is not allowed'
$ChildTimeoutMs = 20000
$PhaseCapSeconds = 600
$MaxAuxProcesses = 4
$PS51 = (Get-Process -Id $PID).Path
if ([IO.Path]::GetFileName($PS51) -ne 'powershell.exe') {
    throw 'Run this driver from ordinary powershell.exe (Windows PowerShell 5.1).'
}

# ---------------------------------------------------------------------------
# Small helper functions (no New-Item -LiteralPath: Windows PowerShell 5.1
# New-Item has no -LiteralPath parameter, so static .NET APIs are used).
# ---------------------------------------------------------------------------
function Write-Text([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, $U8)
}

function New-Directory([string]$Path) {
    return [IO.Directory]::CreateDirectory($Path).FullName
}

function New-CodePointText([int[]]$CodePoints) {
    # Build Unicode text from explicit code points so this PS1 source stays
    # 7-bit ASCII. A Windows PowerShell 5.1 host that decodes the source as ANSI
    # therefore cannot corrupt the intended characters.
    $builder = New-Object System.Text.StringBuilder
    foreach ($codePoint in $CodePoints) {
        if ($codePoint -lt 0 -or $codePoint -gt 0xFFFF) {
            throw ('Unsupported code point for a UTF-16 builder: ' + $codePoint)
        }
        [void]$builder.Append([char]$codePoint)
    }
    return $builder.ToString()
}

function Get-NestedErrorText([object]$Receipt) {
    # Scan every captured nested error, including the guarded-push records, and
    # include type/error-id fields so a policy refusal cannot hide in a nested
    # exception or in an exception type that only differs by class name.
    if ($null -eq $Receipt) { return '' }
    $parts = New-Object System.Collections.ArrayList
    $records = New-Object System.Collections.ArrayList
    [void]$records.Add($Receipt.caught)
    if ($null -ne $Receipt.guarded_push) {
        [void]$records.Add($Receipt.guarded_push.caught)
        [void]$records.Add($Receipt.guarded_push.dot_source_caught)
    }
    foreach ($record in $records) {
        if ($null -eq $record) { continue }
        foreach ($field in @('exception_type', 'message', 'fully_qualified_error_id', 'category', 'script_stack_trace')) {
            $value = [string]$record.$field
            if (-not [string]::IsNullOrEmpty($value)) { [void]$parts.Add($value) }
        }
    }
    return ($parts -join ' | ')
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $text = [IO.File]::ReadAllText($Path)
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return ($text | ConvertFrom-Json)
}

function Read-TextFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return [IO.File]::ReadAllText($Path)
}

function Format-NativeArg([string]$Value) {
    if ($null -eq $Value) { return '""' }
    if ($Value.Length -eq 0) { return '""' }
    if ($Value -match '[\s"]') {
        $escaped = $Value -replace '(\\*)"', '$1$1\"'
        $escaped = $escaped -replace '(\\+)$', '$1$1'
        return '"' + $escaped + '"'
    }
    return $Value
}

function Invoke-BoundedChild {
    param(
        [string]$FilePath,
        [string[]]$ArgumentTexts,
        [int]$TimeoutMs,
        [string]$StdoutPath,
        [string]$StderrPath
    )
    $argLine = ($ArgumentTexts | ForEach-Object { Format-NativeArg $_ }) -join ' '
    $process = Start-Process -FilePath $FilePath -ArgumentList $argLine -NoNewWindow -PassThru `
        -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
    $exited = $process.WaitForExit($TimeoutMs)
    if (-not $exited) {
        try { $process.Kill() | Out-Null } catch { }
        try { $null = $process.WaitForExit(5000) } catch { }
        return [ordered]@{ exit_code = $null; timed_out = $true; pid = $process.Id }
    }
    $process.Refresh()
    return [ordered]@{ exit_code = $process.ExitCode; timed_out = $false; pid = $process.Id }
}

function Test-UnderRoot([string]$Path, [string]$Root) {
    if ([string]::IsNullOrEmpty($Path) -or [string]::IsNullOrEmpty($Root)) { return $false }
    $full = [IO.Path]::GetFullPath($Path)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    return $full.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)
}

function Get-ErrorMessage([object]$Caught) {
    if ($null -eq $Caught) { return '' }
    return [string]$Caught.message
}

function Add-Expect([object]$Condition, [string]$Message) {
    if (-not $Condition) { [void]$script:CurrentFailures.Add($Message) }
}

function Get-WriterStructureFailures {
    param(
        [string]$JsonText,
        [string]$ServerName,
        [string]$PythonCommand,
        [string]$ExpectedCwd,
        [string]$ExpectedFakeRoot
    )
    $problems = @()
    if ([string]::IsNullOrWhiteSpace($JsonText)) {
        return @('writer output is empty')
    }
    $parsed = $null
    try {
        $parsed = $JsonText | ConvertFrom-Json
    }
    catch {
        return @('writer output is not valid JSON: ' + [string]$_.Exception.Message)
    }
    if ($null -eq $parsed) { return @('writer output is null JSON') }
    $topNames = @($parsed.PSObject.Properties.Name)
    if ($topNames.Count -ne 1 -or $topNames[0] -ne 'mcpServers') {
        $problems += 'top-level JSON keys must be exactly mcpServers; observed: ' + ($topNames -join ',')
        return $problems
    }
    $servers = $parsed.mcpServers
    $names = @($servers.PSObject.Properties.Name)
    if ($names.Count -ne 1) {
        $problems += 'expected exactly one server entry; observed ' + $names.Count
        return $problems
    }
    if ($names[0] -ne $ServerName) {
        $problems += 'server name mismatch: ' + $names[0]
    }
    $entry = $servers.PSObject.Properties[$names[0]].Value
    if ($null -eq $entry) {
        $problems += 'server entry is null'
        return $problems
    }
    if ([string]$entry.command -ne $PythonCommand) {
        $problems += 'command mismatch: ' + [string]$entry.command
    }
    $argsJoined = (@($entry.args) -join '|')
    if ($argsJoined -ne '-m|question_research_poc.mcp_server') {
        $problems += 'args mismatch: ' + $argsJoined
    }
    if ([string]$entry.cwd -ne $ExpectedCwd) {
        $problems += 'cwd mismatch: ' + [string]$entry.cwd
    }
    if ([string]$entry.env.PYTHONPATH -ne $ExpectedFakeRoot) {
        $problems += 'env PYTHONPATH mismatch: ' + [string]$entry.env.PYTHONPATH
    }
    return $problems
}

# ---------------------------------------------------------------------------
# Inner per-case harness. It runs one case inside its own powershell.exe child
# so that the target helper can be invoked in-process (needed to observe cwd
# and environment restoration) without letting a helper `exit` terminate the
# outer driver. The inner script is written under the fresh OutputRoot.
# ---------------------------------------------------------------------------
$innerScript = @'
param(
    [Parameter(Mandatory = $true)][string]$CaseJsonPath
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$config = ([IO.File]::ReadAllText($CaseJsonPath)) | ConvertFrom-Json
$caseDir = Split-Path -Parent $CaseJsonPath
$receiptPath = Join-Path $caseDir 'receipt.json'
$beforeReceiptPath = Join-Path $caseDir 'receipt-before.json'

function Write-ReceiptJson([string]$Path, [object]$Object) {
    $text = ($Object | ConvertTo-Json -Depth 12)
    [IO.File]::WriteAllText($Path, $text, $utf8)
}

function Get-ErrorInfo([object]$Record) {
    $type = $null
    $message = $null
    $errorId = $null
    $category = $null
    $stack = $null
    if ($null -ne $Record) {
        if ($null -ne $Record.Exception) {
            $type = $Record.Exception.GetType().FullName
            $message = [string]$Record.Exception.Message
        }
        else {
            $message = [string]$Record
        }
        $errorId = [string]$Record.FullyQualifiedErrorId
        $category = [string]$Record.CategoryInfo.Category
        $stack = [string]$Record.ScriptStackTrace
    }
    return [ordered]@{
        exception_type = $type
        message = $message
        fully_qualified_error_id = $errorId
        category = $category
        script_stack_trace = $stack
    }
}

function Get-State {
    $present = [bool](Test-Path -LiteralPath Env:PYTHONPATH)
    $value = $null
    if ($present) { $value = [string]$env:PYTHONPATH }
    return [ordered]@{
        present = $present
        value = $value
        cwd = (Get-Location).Path
    }
}

$script:receipt = [ordered]@{
    synthetic_only = $true
    case_name = [string]$config.case_name
    wrapper_kind = [string]$config.wrapper_kind
    mode = [string]$config.mode
    ps_version = $PSVersionTable.PSVersion.ToString()
    ps_edition = [string]$PSVersionTable.PSEdition
    python_executable = [string]$config.python
    phase = 'before'
    started_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'")
    finished_utc = $null
    wrapper_exit_observed = $null
    caught = $null
    cwd_before = $null
    cwd_after = $null
    cwd_restored = $null
    pythonpath_present_before = $null
    pythonpath_value_before = $null
    pythonpath_present_after = $null
    pythonpath_value_after = $null
    pythonpath_presence_restored = $null
    pythonpath_value_restored = $null
    stdout_text = $null
    output_file = $null
    output_file_exists = $null
    output_file_bytes = $null
    output_file_sha256 = $null
    output_file_has_bom = $null
    output_file_text = $null
    guarded_push = $null
}
$script:caught = $null
$script:stdoutLines = $null

function Complete-Receipt {
    $stateAfter = Get-State
    $script:receipt.phase = 'after'
    $script:receipt.wrapper_exit_observed = $global:LASTEXITCODE
    $script:receipt.caught = $script:caught
    $script:receipt.cwd_after = $stateAfter.cwd
    $script:receipt.cwd_restored = ($stateAfter.cwd -eq $script:receipt.cwd_before)
    $script:receipt.pythonpath_present_after = $stateAfter.present
    $script:receipt.pythonpath_value_after = $stateAfter.value
    $script:receipt.pythonpath_presence_restored = ($stateAfter.present -eq [bool]$script:receipt.pythonpath_present_before)
    $script:receipt.pythonpath_value_restored = ($stateAfter.value -eq $script:receipt.pythonpath_value_before)
    if ($null -ne $script:stdoutLines -and $null -eq $script:receipt.stdout_text) {
        $script:receipt.stdout_text = (($script:stdoutLines | ForEach-Object { [string]$_ }) -join "`n")
    }
    $script:receipt.finished_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'")
    Write-ReceiptJson $receiptPath $script:receipt
}

Set-Location -LiteralPath ([string]$config.caller)
switch ([string]$config.pythonpath_mode) {
    'present' { $env:PYTHONPATH = 'SYNTHETIC previous Python path' }
    'absent' { Remove-Item -LiteralPath Env:PYTHONPATH -ErrorAction SilentlyContinue }
    'empty' { $env:PYTHONPATH = '' }
    default { throw ('Unknown synthetic pythonpath mode: ' + [string]$config.pythonpath_mode) }
}
$stateBefore = Get-State
$script:receipt.cwd_before = $stateBefore.cwd
$script:receipt.pythonpath_present_before = $stateBefore.present
$script:receipt.pythonpath_value_before = $stateBefore.value
Write-ReceiptJson $beforeReceiptPath $script:receipt

$global:LASTEXITCODE = 29
$wrapperKind = [string]$config.wrapper_kind
$mode = [string]$config.mode

if ($wrapperKind -eq 'cli') {
    $wrapper = [string]$config.wrapper_path
    $python = [string]$config.python
    try {
        if ($mode -eq 'cli-argv') {
            $unicodeArg = ([char]0x4E2D).ToString() + ([char]0x6587).ToString() + ([char]0x53C2).ToString() + ([char]0x6570).ToString()
            $cliArgs = @('--title', 'space value', "it's a 'quoted' value", $unicodeArg, '--flag=value with space')
            $script:stdoutLines = & $wrapper -Python $python -CliArgs $cliArgs
        }
        elseif ($mode -eq 'cli-missing-python') {
            $missing = Join-Path ([string]$config.caller) 'SYNTHETIC-missing-python.exe'
            $script:stdoutLines = & $wrapper -Python $missing -CliArgs @('--list-tools')
        }
        else {
            $script:stdoutLines = & $wrapper -Python $python -CliArgs @('--list-tools')
        }
    }
    catch {
        $script:caught = Get-ErrorInfo $_
    }
    finally {
        try {
            Complete-Receipt
        }
        catch {
            try {
                [IO.File]::WriteAllText((Join-Path $caseDir 'receipt-write-error.txt'), [string]$_, $utf8)
            }
            catch { }
        }
    }
    exit 0
}

if ($wrapperKind -eq 'writer') {
    $wrapper = [string]$config.wrapper_path
    $python = [string]$config.python
    $writerParams = @{ Python = $python }
    if (-not [string]::IsNullOrEmpty([string]$config.server_name)) { $writerParams.ServerName = [string]$config.server_name }
    if (-not [string]::IsNullOrEmpty([string]$config.client)) { $writerParams.Client = [string]$config.client }
    if ([bool]$config.validate) { $writerParams.Validate = $true }
    if (-not [string]::IsNullOrEmpty([string]$config.output_file)) { $writerParams.Output = [string]$config.output_file }
    try {
        $script:stdoutLines = & $wrapper @writerParams
    }
    catch {
        $script:caught = Get-ErrorInfo $_
    }
    if (-not [string]::IsNullOrEmpty([string]$config.output_file)) {
        $outPath = [string]$config.output_file
        $script:receipt.output_file = $outPath
        $exists = [bool](Test-Path -LiteralPath $outPath -PathType Leaf)
        $script:receipt.output_file_exists = $exists
        if ($exists) {
            $bytes = [IO.File]::ReadAllBytes($outPath)
            $script:receipt.output_file_bytes = $bytes.Length
            $hasBom = $false
            if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $hasBom = $true }
            $script:receipt.output_file_has_bom = $hasBom
            $script:receipt.output_file_sha256 = (Get-FileHash -LiteralPath $outPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $script:receipt.output_file_text = [IO.File]::ReadAllText($outPath)
        }
    }
    Complete-Receipt
    exit 0
}

if ($wrapperKind -eq 'guarded-push') {
    $callerPath = [string]$config.caller
    $fixturePath = [string]$config.fixture
    $fakeCopy = [string]$config.fake_copy
    $secondSentinel = [string]$config.second_sentinel
    $mcpMarkerPath = [string]$config.mcp_marker
    Push-Location -LiteralPath $fixturePath
    Push-Location -LiteralPath $callerPath
    $stackBefore = @(Get-Location -Stack)
    $stackBeforePaths = @($stackBefore | ForEach-Object { [string]$_.Path })
    $stackCountBefore = $stackBefore.Count
    $cwdBeforeGuard = (Get-Location).Path
    $pythonPathBeforeGuard = $env:PYTHONPATH
    $dotCaught = $null
    try {
        . $fakeCopy
    }
    catch {
        $dotCaught = Get-ErrorInfo $_
    }
    $guard = [ordered]@{
        dot_source_caught = $dotCaught
        caught = $null
        returned = $null
        cwd_before_guard = $cwdBeforeGuard
        cwd_after = $null
        cwd_preserved = $null
        stack_count_before = $stackCountBefore
        stack_count_after = $null
        stack_preserved = $null
        stack_entries_before = @($stackBeforePaths)
        stack_entries_after = $null
        stack_entries_preserved = $null
        pythonpath_before = [string]$pythonPathBeforeGuard
        pythonpath_after = $null
        pythonpath_preserved = $null
        python_command = [string]$config.python
        mcp_marker = $mcpMarkerPath
        mcp_marker_present = $null
        interpreter_launch_observed = $null
    }
    if ($null -eq $dotCaught) {
        try {
            # Use the real supplied Python plus the synthetic fake package. If
            # the guard wrongly lets Push-Location succeed, the fake MCP child
            # would run and write its marker; a missing cwd must fail first.
            $guard.returned = Test-McpServerListTools -PythonCommand ([string]$config.python) `
                -Cwd (Join-Path $callerPath 'SYNTHETIC missing cwd [x]') -PythonPath ([string]$config.fake_root)
        }
        catch {
            $guard.caught = Get-ErrorInfo $_
        }
    }
    $stackAfter = @(Get-Location -Stack)
    $stackAfterPaths = @($stackAfter | ForEach-Object { [string]$_.Path })
    $guard.cwd_after = (Get-Location).Path
    $guard.cwd_preserved = ($guard.cwd_after -eq $cwdBeforeGuard)
    $guard.stack_count_after = $stackAfter.Count
    $guard.stack_preserved = ($stackAfter.Count -eq $stackCountBefore)
    $guard.stack_entries_after = @($stackAfterPaths)
    $guard.stack_entries_preserved = (($stackBeforePaths -join '|') -eq ($stackAfterPaths -join '|'))
    $guard.pythonpath_after = [string]$env:PYTHONPATH
    $guard.pythonpath_preserved = ($env:PYTHONPATH -eq $pythonPathBeforeGuard)
    $guard.mcp_marker_present = [bool](Test-Path -LiteralPath $mcpMarkerPath -PathType Leaf)
    $guard.interpreter_launch_observed = $guard.mcp_marker_present
    $script:receipt.guarded_push = $guard
    $script:caught = $dotCaught
    try { Pop-Location } catch { }
    try { Pop-Location } catch { }
    Complete-Receipt
    exit 0
}

throw ('Unknown synthetic wrapper kind: ' + $wrapperKind)
'@

# ---------------------------------------------------------------------------
# Preconditions and fresh output root. An existing OutputRoot is refused; no
# cleanup or overwrite of caller data is performed.
# ---------------------------------------------------------------------------
$startedAt = Get-Date
$startedUtc = $startedAt.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'")
$phaseDeadline = $startedAt.AddSeconds($PhaseCapSeconds)

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw ('PythonExecutable must be an existing file: ' + $PythonExecutable)
}
if (Test-Path -LiteralPath $OutputRoot) {
    throw 'OutputRoot must be a new directory; existing paths are neither overwritten nor cleaned.'
}
$output = [IO.Path]::GetFullPath($OutputRoot)
$null = New-Directory $output

$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if (-not [string]::IsNullOrEmpty($SourceRoot)) {
    $projectRoot = [IO.Path]::GetFullPath($SourceRoot)
}
$sourceCli = Join-Path $projectRoot 'scripts\research-poc.ps1'
$sourceWriter = Join-Path $projectRoot 'scripts\write-mcp-config.ps1'
foreach ($sourcePath in @($sourceCli, $sourceWriter)) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw ('Helper script not found under the source root: ' + $sourcePath)
    }
}

$pythonVersionText = ((& $PythonExecutable --version 2>&1 | Out-String).Trim())

# ---------------------------------------------------------------------------
# Windows PowerShell 5.1 may decode a UTF-8-noBOM source with the active ANSI
# code page. This driver keeps its own source 7-bit ASCII and builds the intended
# Unicode test data from explicit code points at runtime, then compares known
# intended code points. No code-page or system setting is changed.
# ---------------------------------------------------------------------------
$unicodeSuffix = New-CodePointText @(0x4E2D, 0x6587)
$cliUnicodeArgument = New-CodePointText @(0x4E2D, 0x6587, 0x53C2, 0x6570)
$customServerName = (New-CodePointText @(0x5408, 0x6210)) + ' Server "quoted" [brackets]'
$unicodeSuffixCodePoints = @($unicodeSuffix.ToCharArray() | ForEach-Object { [int]$_ })
$cliUnicodeCodePoints = @($cliUnicodeArgument.ToCharArray() | ForEach-Object { [int]$_ })
$customServerCodePoints = @($customServerName.ToCharArray() | ForEach-Object { [int]$_ })
if (($unicodeSuffixCodePoints -join ',') -ne '20013,25991') { throw 'Unicode fixture suffix code points are not the intended ones.' }
if (($cliUnicodeCodePoints -join ',') -ne '20013,25991,21442,25968') { throw 'Unicode argument code points are not the intended ones.' }
if (($customServerCodePoints[0..1] -join ',') -ne '21512,25104') { throw 'Unicode server-name code points are not the intended ones.' }

# ---------------------------------------------------------------------------
# Fresh synthetic repository, fake package and caller roots. All paths contain
# spaces plus bracket characters; the fixture name also contains non-ASCII text
# so literal-path handling is exercised.
# ---------------------------------------------------------------------------
$fixture = Join-Path $output ('SYNTHETIC repo [space] ' + $unicodeSuffix)
$scripts = Join-Path $fixture 'scripts'
$srcDir = Join-Path $fixture 'src'
$package = Join-Path $srcDir 'question_research_poc'
$fakeRoot = $srcDir
$caller = Join-Path $output ('SYNTHETIC caller [space] ' + $unicodeSuffix)
$casesRoot = Join-Path $output 'cases'
foreach ($dir in @($fixture, $scripts, $srcDir, $package, $caller, $casesRoot)) {
    $null = New-Directory $dir
}

$fixtureCli = Join-Path $scripts 'research-poc.ps1'
$fixtureWriter = Join-Path $scripts 'write-mcp-config.ps1'
Copy-Item -LiteralPath $sourceCli -Destination $fixtureCli
Copy-Item -LiteralPath $sourceWriter -Destination $fixtureWriter
if ((Get-Sha256 $fixtureCli) -ne (Get-Sha256 $sourceCli)) { throw 'research-poc.ps1 copy hash mismatch' }
if ((Get-Sha256 $fixtureWriter) -ne (Get-Sha256 $sourceWriter)) { throw 'write-mcp-config.ps1 copy hash mismatch' }

$fakeInit = @'
# Synthetic fake package only. This file is never the real question-research-poc.
'@
$fakeCli = @'
# Synthetic fake CLI. Standard library only; serves forwarding checks.
import json
import os
import sys

import question_research_poc


def main():
    marker = os.environ.get("QRP_SYNTHETIC_CLI_MARKER")
    if marker:
        payload = {
            "synthetic_only": True,
            "module_file": os.path.abspath(__file__),
            "package_file": os.path.abspath(question_research_poc.__file__),
            "cwd": os.getcwd(),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "python": sys.executable,
            "argv": sys.argv[1:],
            "sys_path": sys.path[:6],
        }
        with open(marker, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False)
    print("SYNTHETIC fake CLI invoked")
    return int(os.environ.get("QRP_SYNTHETIC_CLI_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
'@
$fakeMcp = @'
# Synthetic fake MCP tool listing. Standard library only; no server is started.
import json
import os
import sys

import question_research_poc

PAYLOADS = {
    "valid-one": '[{"name": "synthetic_tool"}]',
    "valid-multi": '[{"name": "alpha"}, {"name": "beta"}]',
    "empty": "[]",
    "null": "null",
    "string": '"synthetic string"',
    "number": "3",
    "object-count": '{"Count": 3, "error": "SYNTHETIC ERROR"}',
    "object-count-named": '{"Count": 3, "error": "SYNTHETIC ERROR", "name": "synthetic_tool"}',
    "object-name": '{"name": "synthetic_tool"}',
    "malformed": '[{"name": ',
    "invalid-empty-name": '[{"name": ""}]',
    "invalid-space-name": '[{"name": "   "}]',
    "invalid-number-name": '[{"name": 123}]',
    "invalid-missing-name": '[{}]',
}


def main():
    args = sys.argv[1:]
    marker = os.environ.get("QRP_SYNTHETIC_MCP_MARKER")
    payload_name = os.environ.get("QRP_SYNTHETIC_PAYLOAD", "valid-one")
    if marker:
        record = {
            "synthetic_only": True,
            "module_file": os.path.abspath(__file__),
            "package_file": os.path.abspath(question_research_poc.__file__),
            "cwd": os.getcwd(),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "python": sys.executable,
            "argv": args,
            "sys_path": sys.path[:6],
        }
        with open(marker, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False)
    if args != ["--list-tools"]:
        sys.stderr.write("unexpected synthetic MCP argv\n")
        return 9
    payload = PAYLOADS.get(payload_name)
    if payload is None:
        sys.stderr.write("unknown synthetic payload\n")
        return 8
    sys.stdout.write(payload + "\n")
    return int(os.environ.get("QRP_SYNTHETIC_MCP_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
'@
Write-Text (Join-Path $package '__init__.py') $fakeInit
Write-Text (Join-Path $package 'cli.py') $fakeCli
Write-Text (Join-Path $package 'mcp_server.py') $fakeMcp

$innerPath = Join-Path $output 'synthetic-inner.ps1'
Write-Text $innerPath $innerScript
$innerBytes = [IO.File]::ReadAllBytes($innerPath)
foreach ($innerByte in $innerBytes) {
    if ($innerByte -gt 127) {
        throw 'Generated inner harness is not ASCII-safe; an ANSI-decoding host could corrupt it.'
    }
}

$fixtureManifest = [ordered]@{
    synthetic_only = $true
    fixture_root = $fixture
    caller_root = $caller
    fake_package_root = $fakeRoot
    copied_helper_sha256 = [ordered]@{
        'scripts/research-poc.ps1' = (Get-Sha256 $fixtureCli)
        'scripts/write-mcp-config.ps1' = (Get-Sha256 $fixtureWriter)
    }
    source_helper_sha256 = [ordered]@{
        'scripts/research-poc.ps1' = (Get-Sha256 $sourceCli)
        'scripts/write-mcp-config.ps1' = (Get-Sha256 $sourceWriter)
    }
    fake_package_sha256 = [ordered]@{
        'src/question_research_poc/__init__.py' = (Get-Sha256 (Join-Path $package '__init__.py'))
        'src/question_research_poc/cli.py' = (Get-Sha256 (Join-Path $package 'cli.py'))
        'src/question_research_poc/mcp_server.py' = (Get-Sha256 (Join-Path $package 'mcp_server.py'))
    }
    encoding = [ordered]@{
        driver_source_ascii = $true
        unicode_built_from_code_points = $true
        fixture_suffix_codepoints = @($unicodeSuffixCodePoints)
        cli_argument_codepoints = @($cliUnicodeCodePoints)
        custom_server_prefix_codepoints = @($customServerCodePoints[0..1])
    }
}
Write-Text (Join-Path $output 'FIXTURE-MANIFEST.json') (($fixtureManifest | ConvertTo-Json -Depth 8) + "`n")

# ---------------------------------------------------------------------------
# Ambient provider/runtime/source variables are cleared for the child helpers
# without reading any profile. PYTHONHOME is left untouched because the fixed
# interpreter may be an embedded distribution that needs its own home.
# ---------------------------------------------------------------------------
$ambientNames = @(
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY',
    'DEEPSEEK_API_KEY', 'MODEL_PROVIDER', 'QRP_PROVIDER', 'QRP_MODEL',
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
    'PYTHONSTARTUP', 'VIRTUAL_ENV', 'CONDA_PREFIX'
)
foreach ($ambientName in $ambientNames) {
    Remove-Item -LiteralPath ('Env:' + $ambientName) -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath 'Env:PYTHONPATH' -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# Case table. Each case is one serial child chain: the outer driver launches one
# inner powershell.exe, which invokes the helper in-process (plus at most one
# fake Python child). No parallelism and no other hosts are used.
# ---------------------------------------------------------------------------
$cases = @(
    @{ name = 'cli-zero'; kind = 'cli'; mode = 'cli-zero'; pythonpath = 'present'; payload = ''; expect = 'ok' },
    @{ name = 'cli-seven'; kind = 'cli'; mode = 'cli-seven'; pythonpath = 'present'; payload = ''; expect = 'ok' },
    @{ name = 'cli-argv'; kind = 'cli'; mode = 'cli-argv'; pythonpath = 'present'; payload = ''; expect = 'ok' },
    @{ name = 'cli-pythonpath-present'; kind = 'cli'; mode = 'cli-pythonpath-present'; pythonpath = 'present'; payload = ''; expect = 'ok' },
    @{ name = 'cli-pythonpath-absent'; kind = 'cli'; mode = 'cli-pythonpath-absent'; pythonpath = 'absent'; payload = ''; expect = 'ok' },
    @{ name = 'cli-pythonpath-empty'; kind = 'cli'; mode = 'cli-pythonpath-empty'; pythonpath = 'empty'; payload = ''; expect = 'ok' },
    @{ name = 'cli-missing-python'; kind = 'cli'; mode = 'cli-missing-python'; pythonpath = 'present'; payload = ''; expect = 'reject' },
    @{ name = 'writer-stdout'; kind = 'writer'; mode = 'writer-stdout'; pythonpath = 'present'; payload = ''; expect = 'ok' },
    @{ name = 'writer-custom-server'; kind = 'writer'; mode = 'writer-custom-server'; pythonpath = 'present'; payload = ''; expect = 'ok'; server_name = $customServerName },
    @{ name = 'writer-client-generic'; kind = 'writer'; mode = 'writer-client-generic'; pythonpath = 'present'; payload = ''; expect = 'ok'; client = 'generic' },
    @{ name = 'writer-client-codex'; kind = 'writer'; mode = 'writer-client-codex'; pythonpath = 'present'; payload = ''; expect = 'ok'; client = 'codex' },
    @{ name = 'writer-client-claude'; kind = 'writer'; mode = 'writer-client-claude'; pythonpath = 'present'; payload = ''; expect = 'ok'; client = 'claude' },
    @{ name = 'validate-valid-one'; kind = 'writer'; mode = 'validate-valid-one'; pythonpath = 'present'; payload = 'valid-one'; expect = 'ok'; validate = $true; tools = 1 },
    @{ name = 'validate-valid-multi'; kind = 'writer'; mode = 'validate-valid-multi'; pythonpath = 'present'; payload = 'valid-multi'; expect = 'ok'; validate = $true; tools = 2 },
    @{ name = 'validate-payload-empty'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'empty'; expect = 'reject'; validate = $true; fragment = 'returned no tools' },
    @{ name = 'validate-payload-null'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'null'; expect = 'reject'; validate = $true; fragment = 'top-level JSON array' },
    @{ name = 'validate-payload-string'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'string'; expect = 'reject'; validate = $true; fragment = 'top-level JSON array' },
    @{ name = 'validate-payload-number'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'number'; expect = 'reject'; validate = $true; fragment = 'top-level JSON array' },
    @{ name = 'validate-payload-object-count'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'object-count'; expect = 'reject'; validate = $true; fragment = 'top-level JSON array' },
    @{ name = 'validate-payload-object-count-named'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'object-count-named'; expect = 'reject'; validate = $true; fragment = 'top-level JSON array' },
    @{ name = 'validate-payload-object-name'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'object-name'; expect = 'reject'; validate = $true; fragment = 'top-level JSON array' },
    @{ name = 'validate-payload-malformed'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'malformed'; expect = 'reject'; validate = $true; fragment = '' },
    @{ name = 'validate-payload-invalid-empty-name'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'invalid-empty-name'; expect = 'reject'; validate = $true; fragment = 'non-empty string name' },
    @{ name = 'validate-payload-invalid-space-name'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'invalid-space-name'; expect = 'reject'; validate = $true; fragment = 'non-empty string name' },
    @{ name = 'validate-payload-invalid-number-name'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'invalid-number-name'; expect = 'reject'; validate = $true; fragment = 'non-empty string name' },
    @{ name = 'validate-payload-invalid-missing-name'; kind = 'writer'; mode = 'validate-bad'; pythonpath = 'present'; payload = 'invalid-missing-name'; expect = 'reject'; validate = $true; fragment = 'non-empty string name' },
    @{ name = 'validate-nonzero-exit'; kind = 'writer'; mode = 'validate-nonzero-exit'; pythonpath = 'present'; payload = 'valid-one'; expect = 'reject'; validate = $true; fragment = 'exit code 7' },
    @{ name = 'output-nested'; kind = 'writer'; mode = 'output-nested'; pythonpath = 'present'; payload = ''; expect = 'ok'; output_rel = 'out\nested\config.json' },
    @{ name = 'output-existing-parent'; kind = 'writer'; mode = 'output-existing-parent'; pythonpath = 'present'; payload = ''; expect = 'ok'; output_rel = 'out-existing\config.json'; create_parent = $true },
    @{ name = 'output-invalid'; kind = 'writer'; mode = 'output-invalid'; pythonpath = 'present'; payload = ''; expect = 'reject'; output_rel = 'blocker\config.json'; blocked_parent = 'blocker' },
    @{ name = 'guarded-push-missing-cwd'; kind = 'guarded-push'; mode = 'guarded-push-missing-cwd'; pythonpath = 'present'; payload = ''; expect = 'reject' }
)

$script:CurrentFailures = New-Object System.Collections.ArrayList
$script:GenericWriterText = $null
$results = New-Object System.Collections.ArrayList
$firstErrors = New-Object System.Collections.ArrayList
$policyStop = $false
$policyFirstError = $null
$phaseCapHit = $false
$skippedRemaining = 0

function Invoke-Case {
    param([hashtable]$Case)

    $name = [string]$Case.name
    $caseDir = Join-Path $casesRoot $name
    $null = New-Directory $caseDir
    $cliMarker = Join-Path $caseDir 'cli-marker.json'
    $mcpMarker = Join-Path $caseDir 'mcp-marker.json'
    $stdoutLog = Join-Path $caseDir 'inner-stdout.log'
    $stderrLog = Join-Path $caseDir 'inner-stderr.log'
    $receiptPath = Join-Path $caseDir 'receipt.json'
    $beforeReceiptPath = Join-Path $caseDir 'receipt-before.json'
    $configPath = Join-Path $caseDir 'case-config.json'

    $outputFile = $null
    if ($Case.ContainsKey('output_rel')) { $outputFile = Join-Path $caseDir ([string]$Case.output_rel) }
    $blockedParent = $null
    if ($Case.ContainsKey('blocked_parent')) { $blockedParent = Join-Path $caseDir ([string]$Case.blocked_parent) }
    $fakeCopy = $null
    if ($Case.kind -eq 'guarded-push') {
        $fakeCopy = Join-Path $scripts 'fakecopy-write-mcp-config.ps1'
        $wrapperText = [IO.File]::ReadAllText($fixtureWriter)
        $mainMarker = '$config = New-McpConfig'
        $markerIndex = $wrapperText.IndexOf($mainMarker)
        if ($markerIndex -lt 0) {
            throw 'Cannot locate the writer main-body marker for the guarded-push fake copy.'
        }
        Write-Text $fakeCopy $wrapperText.Substring(0, $markerIndex)
    }
    if ($Case.kind -eq 'writer' -and $Case.ContainsKey('create_parent') -and [bool]$Case.create_parent -and $null -ne $outputFile) {
        $parent = Split-Path -Parent $outputFile
        if (-not [string]::IsNullOrEmpty($parent)) { $null = New-Directory $parent }
    }
    if ($Case.kind -eq 'writer' -and $null -ne $blockedParent) {
        Write-Text $blockedParent 'SYNTHETIC blocking file; the wrapper must fail instead of replacing it.'
    }

    $serverName = ''
    if ($Case.ContainsKey('server_name')) { $serverName = [string]$Case.server_name }
    $client = ''
    if ($Case.ContainsKey('client')) { $client = [string]$Case.client }
    $validate = $false
    if ($Case.ContainsKey('validate')) { $validate = [bool]$Case.validate }
    $wrapperPath = $fixtureWriter
    if ($Case.kind -eq 'cli') { $wrapperPath = $fixtureCli }

    $caseConfig = [ordered]@{
        case_name = $name
        wrapper_kind = [string]$Case.kind
        mode = [string]$Case.mode
        wrapper_path = $wrapperPath
        python = $PythonExecutable
        caller = $caller
        fixture = $fixture
        fake_root = $fakeRoot
        pythonpath_mode = [string]$Case.pythonpath
        server_name = $serverName
        client = $client
        validate = $validate
        output_file = $outputFile
        blocked_parent = $blockedParent
        fake_copy = $fakeCopy
        second_sentinel = $fixture
        mcp_marker = $mcpMarker
    }
    Write-Text $configPath (($caseConfig | ConvertTo-Json -Depth 6) + "`n")

    $env:QRP_SYNTHETIC_CLI_MARKER = $cliMarker
    $env:QRP_SYNTHETIC_MCP_MARKER = $mcpMarker
    $env:QRP_SYNTHETIC_PAYLOAD = 'valid-one'
    if ($Case.ContainsKey('payload') -and -not [string]::IsNullOrEmpty([string]$Case.payload)) {
        $env:QRP_SYNTHETIC_PAYLOAD = [string]$Case.payload
    }
    $env:QRP_SYNTHETIC_CLI_EXIT = '0'
    if ($Case.mode -eq 'cli-seven') { $env:QRP_SYNTHETIC_CLI_EXIT = '7' }
    $env:QRP_SYNTHETIC_MCP_EXIT = '0'
    if ($Case.mode -eq 'validate-nonzero-exit') { $env:QRP_SYNTHETIC_MCP_EXIT = '7' }

    $watch = [Diagnostics.Stopwatch]::StartNew()
    $run = Invoke-BoundedChild -FilePath $PS51 -ArgumentTexts @('-NoProfile', '-File', $innerPath, '-CaseJsonPath', $configPath) `
        -TimeoutMs $ChildTimeoutMs -StdoutPath $stdoutLog -StderrPath $stderrLog
    $watch.Stop()

    $receipt = Read-JsonFile $receiptPath
    $beforeReceipt = Read-JsonFile $beforeReceiptPath
    $stdoutText = Read-TextFile $stdoutLog
    $stderrText = Read-TextFile $stderrLog

    $script:CurrentFailures = New-Object System.Collections.ArrayList
    if ($run.timed_out) { Add-Expect $false ('per-child timeout of ' + $ChildTimeoutMs + ' ms exceeded') }

    # Inner-host completion exit. Normal harness success is 0. A CLI case may
    # legitimately terminate its hosting child with the helper's own exit code
    # because the helper preserves `exit $LASTEXITCODE`; any other nonzero host
    # exit after a receipt is a harness failure and must not pass.
    $productExitObserved = $null
    if ($null -ne $receipt) { $productExitObserved = [int]$receipt.wrapper_exit_observed }
    $hostExit = $run.exit_code
    $hostExitExplained = $false
    if ($null -eq $hostExit) {
        Add-Expect $false 'inner host exit code was not observed'
    }
    elseif ($hostExit -eq 0) {
        $hostExitExplained = $true
    }
    elseif ($Case.kind -eq 'cli' -and $null -ne $receipt -and $hostExit -eq $productExitObserved) {
        $hostExitExplained = $true
    }
    else {
        Add-Expect $false ('inner host exited ' + $hostExit + ' after writing a receipt; expected 0 (only a CLI helper exit ' + [string]$productExitObserved + ' may be carried)')
    }

    # Scan every captured nested error (including guarded_push.caught and
    # guarded_push.dot_source_caught) and their type/error-id fields before any
    # expected-negative classification. A genuine permission/policy refusal
    # stops the phase with the first original error preserved.
    $nestedErrorText = Get-NestedErrorText $receipt
    $policyText = ''
    foreach ($candidateText in @($stderrText, $stdoutText, $nestedErrorText)) {
        if (-not [string]::IsNullOrEmpty($candidateText) -and $candidateText -match $PolicyPattern) {
            $policyText = $candidateText
            break
        }
    }
    if (-not [string]::IsNullOrEmpty($policyText)) {
        return [ordered]@{
            name = $name
            kind = [string]$Case.kind
            mode = [string]$Case.mode
            expected = [string]$Case.expect
            passed = $false
            policy_block = $true
            policy_error = ('Policy/permission refusal observed in case ' + $name + ': ' + $policyText)
            first_original_error = $policyText
            failures = @('policy/permission refusal; affected native phase stopped without retry')
            duration_ms = [int]$watch.ElapsedMilliseconds
            inner_exit = $run.exit_code
            host_exit_explained = $hostExitExplained
            timed_out = $run.timed_out
            receipt_present = ($null -ne $receipt)
            before_receipt_present = ($null -ne $beforeReceipt)
        }
    }

    Add-Expect ($null -ne $receipt) 'missing post-invocation receipt; caller-finally state was not observable'
    if ($null -ne $receipt) {
        Add-Expect ($receipt.cwd_restored -eq $true) ('cwd not restored; after=' + [string]$receipt.cwd_after)
        Add-Expect ($receipt.pythonpath_presence_restored -eq $true) 'PYTHONPATH presence not restored'
        Add-Expect ($receipt.pythonpath_value_restored -eq $true) ('PYTHONPATH value not restored; before=' + [string]$receipt.pythonpath_value_before + ' after=' + [string]$receipt.pythonpath_value_after)
    }

    if ($Case.kind -eq 'cli') {
        if ($Case.mode -eq 'cli-missing-python') {
            $failed = ($null -ne $receipt.caught) -or ([int]$receipt.wrapper_exit_observed -ne 0)
            Add-Expect $failed 'a missing Python executable must fail, not report success'
            Add-Expect (-not (Test-Path -LiteralPath $cliMarker)) 'missing Python unexpectedly launched the fake package'
        }
        else {
            Add-Expect (Test-Path -LiteralPath $cliMarker) 'fake CLI marker missing'
            if (Test-Path -LiteralPath $cliMarker) {
                $marker = Read-JsonFile $cliMarker
                Add-Expect ([bool]$marker.synthetic_only) 'fake CLI marker is not marked synthetic'
                Add-Expect ([string]$marker.cwd -eq $caller) ('child cwd mismatch: ' + [string]$marker.cwd)
                Add-Expect (Test-UnderRoot ([string]$marker.module_file) $fakeRoot) 'CLI module file is outside the fake root'
                Add-Expect (Test-UnderRoot ([string]$marker.package_file) $fakeRoot) 'package file is outside the fake root'
                Add-Expect (([IO.Path]::GetFullPath([string]$marker.python) -eq [IO.Path]::GetFullPath($PythonExecutable))) 'child used an unexpected interpreter'
                $expectedArgs = @('--list-tools')
                if ($Case.mode -eq 'cli-argv') {
                    $expectedArgs = @('--title', 'space value', "it's a 'quoted' value", $cliUnicodeArgument, '--flag=value with space')
                }
                $observedArgv = @($marker.argv)
                Add-Expect (($observedArgv -join '|') -eq ($expectedArgs -join '|')) ('argv did not round-trip: ' + ($observedArgv -join '|'))
                if ($Case.mode -eq 'cli-argv' -and $observedArgv.Count -gt 3) {
                    $observedUnicodeCodePoints = @(([string]$observedArgv[3]).ToCharArray() | ForEach-Object { [int]$_ })
                    Add-Expect (($observedUnicodeCodePoints -join ',') -eq '20013,25991,21442,25968') ('forwarded Unicode argument code points mismatch: ' + ($observedUnicodeCodePoints -join ','))
                }
                $expectedPythonPath = $fakeRoot
                if ([string]$Case.pythonpath -eq 'present') { $expectedPythonPath = $fakeRoot + ';' + 'SYNTHETIC previous Python path' }
                Add-Expect ([string]$marker.pythonpath -eq $expectedPythonPath) ('child PYTHONPATH mismatch: ' + [string]$marker.pythonpath)
                Add-Expect ((@($marker.sys_path) -contains $fakeRoot)) 'fake package root is not present on sys.path'
            }
            $expectedExit = 0
            if ($Case.mode -eq 'cli-seven') { $expectedExit = 7 }
            Add-Expect ([int]$receipt.wrapper_exit_observed -eq $expectedExit) ('wrapper exit mismatch: observed ' + [string]$receipt.wrapper_exit_observed + ', expected ' + $expectedExit)
        }
    }

    if ($Case.kind -eq 'writer') {
        $isValidate = [bool]$Case.validate
        $isBad = ([string]$Case.expect -eq 'reject')
        $isOutput = $Case.ContainsKey('output_rel')

        if ($isValidate) {
            Add-Expect (Test-Path -LiteralPath $mcpMarker) 'fake MCP marker missing'
            if (Test-Path -LiteralPath $mcpMarker) {
                $marker = Read-JsonFile $mcpMarker
                Add-Expect ([bool]$marker.synthetic_only) 'fake MCP marker is not marked synthetic'
                Add-Expect (Test-UnderRoot ([string]$marker.module_file) $fakeRoot) 'MCP module file is outside the fake root'
                Add-Expect (Test-UnderRoot ([string]$marker.package_file) $fakeRoot) 'MCP package file is outside the fake root'
                Add-Expect ([string]$marker.cwd -eq $fixture) ('MCP child cwd mismatch: ' + [string]$marker.cwd)
                Add-Expect ((@($marker.argv) -join '|') -eq '--list-tools') ('MCP argv mismatch: ' + (@($marker.argv) -join '|'))
                Add-Expect ([string]$marker.pythonpath -eq ($fakeRoot + ';' + 'SYNTHETIC previous Python path')) ('MCP child PYTHONPATH mismatch: ' + [string]$marker.pythonpath)
                Add-Expect ((@($marker.sys_path) -contains $fakeRoot)) 'fake package root is not present on the MCP child sys.path'
            }
            if ($isBad) {
                Add-Expect ($null -ne $receipt.caught) 'invalid or failing MCP payload was accepted instead of rejected'
                if ($null -ne $receipt.caught -and -not [string]::IsNullOrEmpty([string]$Case.fragment)) {
                    Add-Expect ((Get-ErrorMessage $receipt.caught) -match [string]$Case.fragment) ('rejection message mismatch: ' + (Get-ErrorMessage $receipt.caught))
                }
                Add-Expect ($stdoutText -notmatch 'Validated ') 'a rejected MCP payload was reported as validated'
            }
            else {
                Add-Expect ($null -eq $receipt.caught) ('valid MCP payload failed: ' + (Get-ErrorMessage $receipt.caught))
                $expectedLine = 'Validated lecture-extract MCP server for generic client: ' + [int]$Case.tools + ' tools'
                Add-Expect ($stdoutText -match [regex]::Escape($expectedLine)) ('missing validation confirmation: ' + $expectedLine)
                $jsonText = [string]$receipt.stdout_text
                $problems = Get-WriterStructureFailures -JsonText $jsonText -ServerName 'lecture-extract' -PythonCommand $PythonExecutable -ExpectedCwd $fixture -ExpectedFakeRoot $fakeRoot
                foreach ($problem in $problems) { Add-Expect $false $problem }
            }
        }
        elseif ($isOutput) {
            if ($isBad) {
                Add-Expect ($null -ne $receipt.caught) 'an unwritable output path was accepted'
                Add-Expect (-not (Test-Path -LiteralPath $outputFile)) 'rejected output path still produced a file'
                Add-Expect ((Test-Path -LiteralPath $blockedParent -PathType Leaf)) 'the synthetic blocking parent file was removed or replaced'
            }
            else {
                Add-Expect ($null -eq $receipt.caught) ('explicit output write failed: ' + (Get-ErrorMessage $receipt.caught))
                Add-Expect ($receipt.output_file_exists -eq $true) 'explicit output file was not created'
                if ($receipt.output_file_exists -eq $true) {
                    Add-Expect ($receipt.output_file_has_bom -eq $false) 'explicit output file has a UTF-8 BOM'
                    $fileText = [string]$receipt.output_file_text
                    Add-Expect ($fileText -eq [string]$script:GenericWriterText) 'explicit output file differs from the stdout JSON contract'
                    $problems = Get-WriterStructureFailures -JsonText $fileText -ServerName 'lecture-extract' -PythonCommand $PythonExecutable -ExpectedCwd $fixture -ExpectedFakeRoot $fakeRoot
                    foreach ($problem in $problems) { Add-Expect $false $problem }
                    Add-Expect ($stdoutText -match 'Wrote generic MCP config to') 'missing write confirmation on stdout'
                }
            }
        }
        else {
            Add-Expect ($null -eq $receipt.caught) ('writer invocation failed unexpectedly: ' + (Get-ErrorMessage $receipt.caught))
            Add-Expect (-not (Test-Path -LiteralPath $mcpMarker)) 'a non-validate writer call launched the fake MCP module'
            $expectedName = 'lecture-extract'
            if ($Case.ContainsKey('server_name')) { $expectedName = [string]$Case.server_name }
            $jsonText = [string]$receipt.stdout_text
            $problems = Get-WriterStructureFailures -JsonText $jsonText -ServerName $expectedName -PythonCommand $PythonExecutable -ExpectedCwd $fixture -ExpectedFakeRoot $fakeRoot
            foreach ($problem in $problems) { Add-Expect $false $problem }
            if ($name -eq 'writer-stdout') {
                $script:GenericWriterText = $jsonText
            }
            if ($name -eq 'writer-client-codex' -or $name -eq 'writer-client-claude') {
                Add-Expect ($jsonText -eq [string]$script:GenericWriterText) 'the client label changed the generic JSON contract'
            }
            if ($name -eq 'writer-custom-server' -and $null -eq $receipt.caught) {
                try {
                    $observedServers = @((([string]$receipt.stdout_text) | ConvertFrom-Json).mcpServers.PSObject.Properties.Name)
                    if ($observedServers.Count -eq 1) {
                        $observedServerCodePoints = @(([string]$observedServers[0]).ToCharArray() | ForEach-Object { [int]$_ })
                        Add-Expect (($observedServerCodePoints[0..1] -join ',') -eq '21512,25104') ('custom server-name code points mismatch: ' + ($observedServerCodePoints[0..1] -join ','))
                    }
                    else {
                        Add-Expect $false ('custom server JSON key count is not one: ' + $observedServers.Count)
                    }
                }
                catch {
                    Add-Expect $false ('custom server JSON could not be parsed for a code-point check: ' + [string]$_.Exception.Message)
                }
            }
        }
    }

    if ($Case.kind -eq 'guarded-push') {
        $guard = $receipt.guarded_push
        Add-Expect ($null -ne $guard) 'guarded-push section missing from receipt'
        if ($null -ne $guard) {
            Add-Expect ($null -eq $guard.dot_source_caught) ('dot-sourcing the functions-only copy failed: ' + (Get-ErrorMessage $guard.dot_source_caught))
            Add-Expect ($null -ne $guard.caught) 'missing cwd did not fail as expected'
            if ($null -ne $guard.caught) {
                $guardMessage = ([string]$guard.caught.message + ' ' + [string]$guard.caught.exception_type + ' ' + [string]$guard.caught.fully_qualified_error_id)
                Add-Expect ($guardMessage -match 'Cannot find path|does not exist|ItemNotFoundException|ObjectNotFound') ('unexpected guarded-push failure: ' + $guardMessage)
            }
            Add-Expect ($null -eq $guard.returned) 'missing cwd returned a tool count instead of failing'
            Add-Expect ($guard.cwd_preserved -eq $true) ('caller cwd not preserved: ' + [string]$guard.cwd_after)
            Add-Expect ($guard.stack_preserved -eq $true) ('caller location stack count changed: ' + [string]$guard.stack_count_before + ' -> ' + [string]$guard.stack_count_after)
            Add-Expect ($guard.stack_entries_preserved -eq $true) 'caller location stack entries or order changed after the failed Push-Location'
            Add-Expect ([int]$guard.stack_count_before -ge 1) 'the synthetic caller did not have a pre-existing location stack'
            Add-Expect ($guard.pythonpath_preserved -eq $true) 'PYTHONPATH was not restored after a failed Push-Location'
            Add-Expect ([string]$guard.python_command -eq $PythonExecutable) 'guarded-push did not use the supplied fixed Python executable'
            Add-Expect ($guard.mcp_marker_present -eq $false) 'the fake MCP child launched despite the missing cwd; an unexpected launch is a failure'
            Add-Expect ($guard.interpreter_launch_observed -eq $false) 'an interpreter launch was observed for the guarded-push negative control'
        }
    }

    $passed = ($script:CurrentFailures.Count -eq 0)
    $entry = [ordered]@{
        name = $name
        kind = [string]$Case.kind
        mode = [string]$Case.mode
        expected = [string]$Case.expect
        passed = $passed
        policy_block = $false
        failures = @($script:CurrentFailures)
        duration_ms = [int]$watch.ElapsedMilliseconds
        inner_exit = $run.exit_code
        host_exit_expected_normal = 0
        host_exit_explained = $hostExitExplained
        product_exit_observed = $productExitObserved
        timed_out = $run.timed_out
        receipt_present = ($null -ne $receipt)
        before_receipt_present = ($null -ne $beforeReceipt)
        cwd_before = $null
        cwd_after = $null
        pythonpath_value_before = $null
        pythonpath_value_after = $null
        pythonpath_presence_restored = $null
    }
    if ($null -ne $receipt) {
        $entry.cwd_before = $receipt.cwd_before
        $entry.cwd_after = $receipt.cwd_after
        $entry.pythonpath_value_before = $receipt.pythonpath_value_before
        $entry.pythonpath_value_after = $receipt.pythonpath_value_after
        $entry.pythonpath_presence_restored = $receipt.pythonpath_presence_restored
    }
    return $entry
}

$harnessError = $null
try {
    foreach ($case in $cases) {
        if ($phaseCapHit) {
            $skippedRemaining++
            continue
        }
        if ((Get-Date) -gt $phaseDeadline) {
            $phaseCapHit = $true
            $skippedRemaining++
            continue
        }
        $result = Invoke-Case -Case $case
        [void]$results.Add($result)
        if ($result.policy_block) {
            $policyStop = $true
            $policyFirstError = [string]$result.policy_error
            $phaseCapHit = $false
            break
        }
        if (-not $result.passed) {
            if ($firstErrors.Count -lt 10) {
                [void]$firstErrors.Add(('[' + $result.name + '] ' + (($result.failures) -join '; ')))
            }
        }
    }
}
catch {
    $harnessError = [string]$_
    if ($harnessError -match $PolicyPattern) {
        $policyStop = $true
        $policyFirstError = $harnessError
    }
}

$passedCount = 0
$failedCount = 0
foreach ($result in $results) {
    if ($result.passed) { $passedCount++ } else { $failedCount++ }
}
$totalFailed = $failedCount + $skippedRemaining
if ($null -ne $harnessError -and $skippedRemaining -eq 0 -and $results.Count -eq 0) {
    $totalFailed = $totalFailed + 1
}

$finishedAt = Get-Date
$resultDocument = [ordered]@{
    synthetic_only = $true
    stage = 'stage2_native_phase'
    entry = 'tests/test_qrp_wrappers_synthetic.ps1'
    started_utc = $startedUtc
    finished_utc = $finishedAt.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'")
    duration_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
    powershell = [ordered]@{
        executable = $PS51
        version = $PSVersionTable.PSVersion.ToString()
        edition = [string]$PSVersionTable.PSEdition
    }
    python = [ordered]@{
        executable = [IO.Path]::GetFullPath($PythonExecutable)
        version = $pythonVersionText
    }
    source_root = $projectRoot
    output_root = $output
    fixture_root = $fixture
    fake_package_root = $fakeRoot
    caller_root = $caller
    limits = [ordered]@{
        real_mcp = $false
        real_model = $false
        network = $false
        installed_wheel = $false
        cross_platform = $false
        security_settings_changed = $false
        os_isolation_measured = $false
        peak_memory_measured = $false
        thread_count_measured = $false
    }
    child_timeout_ms = $ChildTimeoutMs
    phase_cap_seconds = $PhaseCapSeconds
    max_aux_processes_by_design = $MaxAuxProcesses
    serial_children = $true
    host_exit_expectation = [ordered]@{
        normal_success = 0
        cli_may_carry_helper_exit = $true
        assertion = 'inner host exit must be 0, or for a CLI case equal the recorded helper exit code'
    }
    unicode_codepoints = [ordered]@{
        fixture_suffix = @($unicodeSuffixCodePoints)
        cli_argument = @($cliUnicodeCodePoints)
        custom_server_prefix = @($customServerCodePoints[0..1])
    }
    cases_total = $results.Count
    passed = $passedCount
    failed = $failedCount
    skipped = $skippedRemaining
    phase_cap_hit = $phaseCapHit
    policy_stop = $policyStop
    policy_first_error = $policyFirstError
    harness_error = $harnessError
    first_errors = @($firstErrors)
    cases = @($results)
}
Write-Text (Join-Path $output 'RESULT.json') (($resultDocument | ConvertTo-Json -Depth 12) + "`n")

if ($policyStop) {
    Write-Output ('POLICY STOP: affected native phase stopped without retry: ' + $policyFirstError)
    exit 3
}
if ($null -ne $harnessError) {
    Write-Output ('HARNESS ERROR: ' + $harnessError)
    exit 2
}
if ($totalFailed -gt 0) {
    Write-Output ('FAIL ' + $totalFailed + ' of ' + $results.Count + ' synthetic cases; see RESULT.json')
    exit 1
}
Write-Output ('PASS ' + $passedCount + ' synthetic PowerShell helper cases; no real MCP, model, client registration or network.')
exit 0
