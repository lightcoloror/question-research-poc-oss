# Portable PowerShell helper wrappers

> **Notice: Source-Only Publication and Unexecuted Status**
> The scripts and synthetic driver in this edition are published as reviewed candidate source files. Prior execution of `tests/test_qrp_wrappers_synthetic.ps1` on native Windows PowerShell 5.1 was halted by the system `AuthorizationManager` before the driver started (0 cases executed). That prior environment refusal is retained as-is; this release does not bypass execution policies, alter host security settings, or rebuild environments. The earlier broader bundle has 62 recorded static checks; they are reused as scoped source evidence, not as 62 native test cases or Windows PowerShell 5.1 verification. No target-native execution pass or running feature certificate is claimed.

## Overview

This distribution includes two portable Windows PowerShell 5.1 helper wrappers and a dedicated synthetic contract-check driver:

- `scripts/research-poc.ps1`: CLI forwarder for the repository Python CLI.
- `scripts/write-mcp-config.ps1`: Generates standard `mcpServers` JSON configuration pointing to the local checkout. See [mcp-config-helper.md](mcp-config-helper.md) for detailed configuration documentation.
- `tests/test_qrp_wrappers_synthetic.ps1`: Synthetic test driver designed to test contract invariants against fake standard-library modules without importing the real package.

## `scripts/research-poc.ps1`

Forwards arguments to the project CLI module `question_research_poc.cli`.

| Parameter | Meaning |
| --- | --- |
| `-CliArgs` | Array of arguments passed to `python -m question_research_poc.cli` via `@CliArgs`. Intended to pass arguments through, but native quoting and argument round-tripping remain unverified (including double quotes). |
| `-Python` | Python executable to invoke; defaults to `python` |

The wrapper resolves its project root from `$PSScriptRoot`, prepends `src` to `$env:PYTHONPATH`, launches the target Python module, propagates `$LASTEXITCODE`, and restores previous `$env:PYTHONPATH` in a `finally` block.

**Security and Boundary Notes:**
- The wrapper forwards commands to the project Python CLI, which may perform computation, network requests, or model invocations depending on the invoked CLI arguments. The wrapper itself does not grant elevated permissions or restrict underlying CLI operations.
- Non-zero exit code forwarding and environment restoration reflect source-level design patterns rather than verified runtime behavior.

### Example Invocation

```powershell
powershell.exe -NoProfile -File scripts/research-poc.ps1 -CliArgs @('--help')
```

## `scripts/write-mcp-config.ps1`

Writes an `mcpServers` JSON configuration snippet pointing to the local checkout's optional MCP server. Detailed documentation is provided in [mcp-config-helper.md](mcp-config-helper.md).

| Parameter | Meaning |
| --- | --- |
| `-Client` | Label only: `generic` (default), `codex`, or `claude`. Emits identical generic JSON shape without client-specific format conversion (not Codex TOML). |
| `-Output` | Optional destination path. Default writes to standard output. When specified, writes or completely overwrites the target file as UTF-8 without BOM; **does not merge into existing configurations**. |
| `-ServerName` | Server key under `mcpServers`; defaults to `lecture-extract`. |
| `-Python` | Python executable written to the `command` field; defaults to `python`. |
| `-Validate` | Opt-in switch: launches `python -m question_research_poc.mcp_server --list-tools` and requires a valid non-empty tool listing array. |

Both helper scripts must be present in `scripts/` when executing the synthetic driver.

## Synthetic Test Driver (`tests/test_qrp_wrappers_synthetic.ps1`)

The synthetic driver tests the two PowerShell helper scripts against defined contract requirements. It is designed to run under standard Windows PowerShell 5.1 (Desktop edition, `powershell.exe`).

```powershell
powershell.exe -NoProfile -File tests/test_qrp_wrappers_synthetic.ps1 `
  -PythonExecutable <path-to-python.exe> -OutputRoot <new-directory>
```

### Safety and Isolation Mechanisms
- **Strict Host Verification:** Checks `$PSVersionTable.PSVersion.Major -eq 5` and `$PSVersionTable.PSEdition -eq 'Desktop'`, and verifies the host process is `powershell.exe`. It strictly refuses other hosts (such as PowerShell 7+ Core). Static source parsing under other versions does not constitute native test execution.
- **Intended Fake-Module Isolation:** Refuses an existing `-OutputRoot` to prevent data loss. The source is designed to set up a fresh synthetic repository containing a standard-library fake package, without importing the real package or starting real MCP transports (an unexecuted driver does not prove hermetic OS/runtime isolation).
- **Bounded Execution:** Enforces a 20-second timeout per child process and a 600-second cumulative phase cap.
- **Fail-Closed on Policy Refusal:** Monitors error records for security and policy exceptions (`AuthorizationManager`, `UnauthorizedAccess`, `ExecutionPolicy`). If a policy refusal occurs, it halts the native phase immediately without retries or bypass attempts.
- **Operator-Local Artifacts:** Generated reports and receipts contain operator-local paths and command strings; they are not sanitized public fixtures.

### Contract Coverage
The driver defines test cases for CLI exit code propagation (`0` and `7`), Unicode/quote/space argument forwarding (using single quotes and spaces), `PYTHONPATH` preservation and restoration across missing/empty states, custom server names and client labels, overwrite behavior, invalid MCP payloads, and location stack preservation on missing working directories.

### Intended Driver Exit Codes (Completed-Run Path)

These exit codes describe the intended completed-report path; early host, argument, or setup guards can throw terminating exceptions before final exit dispatch:
- `0`: All synthetic assertions passed.
- `1`: Assertion failure or phase timeout cap reached.
- `2`: Harness setup or parameter validation error.
- `3`: Policy, authorization, or permission refusal observed (no retry).

## Source Provenance and License

This software is distributed under the [Apache-2.0 License](../LICENSE).

- **Original Helper Source:** Adapted from first-party QRP helper commit `7e13f2acd3175dea0538ce78a11bb9ca081a6668`. The portable source bytes here are adapted and not claimed to be identical to the original Git commit.
- **Driver Architecture:** The synthetic harness pattern (fresh scratch directory, isolated fake package, bounded serial execution, fail-closed policy handling) is inspired by the Apache-2.0 `web-content-fetcher-oss` project at commit `c9432cd98bafa69523722e3ab8e081f373fcb7fb`. No WCF implementation, user interface, or third-party binaries are vendored or executed.

### File Manifest and Hashes

| Path | Bytes | SHA256 |
| --- | --- | --- |
| `scripts/research-poc.ps1` | 599 | `cdfc2e05cfd45727b52e792d5922678af99a4f9e2b90c5d2609286db1eba0eac` |
| `scripts/write-mcp-config.ps1` | — | `5cf81d91d0b4ee539428f19de2e5587618080f7409a99ae66352ef950938c31d` |
| `tests/test_qrp_wrappers_synthetic.ps1` | 58,048 | `05899cc869feae5d3e779481b3a4149abb22ddd34638d90cc97dac005a46b4e7` |

## Checks for this source publication

Both newly included script sources passed non-executing `ParseInput` checks under PowerShell 7.5.2 Core, with zero reported syntax errors. This is not Windows PowerShell 5.1 verification or execution of either script. The native driver, fake modules, MCP listing, real server and CLI were not run for this source publication.
