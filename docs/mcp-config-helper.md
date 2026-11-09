# MCP Configuration Generator Helper

## Overview

The PowerShell helper `scripts/write-mcp-config.ps1` produces a standard `mcpServers` JSON configuration snippet pointing to the current repository checkout's optional `question_research_poc.mcp_server`.

By default, the script generates JSON and emits it directly to standard output. In this default mode, the script does not modify any client configuration files, does not launch a Python process, and does not start an MCP server.

The script calculates paths dynamically from its location (`$PSScriptRoot`), deriving `$projectRoot` and `$srcRoot` (`src/`). Consequently, the emitted `cwd` and `env.PYTHONPATH` fields contain absolute filesystem paths pointing to the operator's local checkout. This output is designed for operator-local client configuration rather than as a sanitized public fixture.

## Parameters

| Parameter | Type / Values | Default | Description |
|---|---|---|---|
| `-Client` | `generic`, `codex`, `claude` | `generic` | **Label only.** The label is shown when writing a file or validating; default stdout-only generation does not show it. The generated JSON structure remains identical across all selections. The script does not convert to proprietary formats (such as Codex TOML), register tools, or perform client logins. |
| `-ServerName` | `string` | `lecture-extract` | Key name placed under `mcpServers` in the emitted JSON. `lecture-extract` is the legacy default key; operators can override this to suit their client setup. |
| `-Python` | `string` | `python` | Path or command name for the Python executable written to the `command` field. The script does not install or search for Python. Optional `-Validate` checks only the selected interpreter’s tool-listing command. |
| `-Output` | `string` | `""` (stdout) | Optional destination path (relative or absolute). Missing parent directories are created automatically. Writes UTF-8 without BOM. **Warning:** Overwrites the target file completely; does not merge into existing configurations. |
| `-Validate` | `switch` | `False` | **Opt-in validation only.** Executes `$Python -m question_research_poc.mcp_server --list-tools` against the local checkout to check basic tool listing before writing or printing. |

## Usage Examples

### 1. Default Output to Standard Output

Emit the snippet to the terminal console without writing any files or invoking Python:

```powershell
powershell -NoProfile -File scripts/write-mcp-config.ps1
```

Generated stdout structure:

```json
{
  "mcpServers": {
    "lecture-extract": {
      "command": "python",
      "args": [
        "-m",
        "question_research_poc.mcp_server"
      ],
      "cwd": "<local-checkout-root>",
      "env": {
        "PYTHONPATH": "<local-checkout-root>/src"
      }
    }
  }
}
```

### 2. Write to a Dedicated Operator File

Write the configuration directly to a new file, specifying a custom server name:

```powershell
powershell -NoProfile -File scripts/write-mcp-config.ps1 -ServerName "qrp-local" -Output "config/mcp-servers.json"
```

> **Warning on File Overwrite:** `-Output` writes the entire JSON document as a complete file using UTF-8 without BOM. It does not parse or merge into existing client configuration files (such as an existing Claude desktop configuration or custom client JSON). Target a dedicated file or manually merge the resulting snippet.

### 3. Optional Tool Listing Validation

Verify that the local environment can execute the module's tool discovery before outputting:

```powershell
powershell -NoProfile -File scripts/write-mcp-config.ps1 -Validate
```

When `-Validate` is specified, the script:
1. Temporarily prepends the local checkout's `src/` to `$env:PYTHONPATH` and pushes location to `$projectRoot`.
2. Invokes `& $Python -m question_research_poc.mcp_server --list-tools`.
3. Asserts the command exits with code 0, prints a top-level non-empty JSON array, and each tool object possesses a non-empty string `name`.
4. Restores `$env:PYTHONPATH` and the working directory in a `finally` block.

`-Validate` tests only local CLI tool listing (`--list-tools`). It does not establish a persistent client connection, start the FastMCP transport, or register the server with an external application.

## Operational & Verification Boundaries

- **Source Provenance:** Adapted from first-party QRP helper source (SHA256: `5cf81d91d0b4ee539428f19de2e5587618080f7409a99ae66352ef950938c31d`). The adapted source is frozen and not claimed to be identical to historical Git blobs or backed by prior external sign-off.
- **Unverified Runtime Status:** Execution under diverse PowerShell versions (Windows PowerShell 5.1, PowerShell 7+, non-Windows platforms) has not been verified. Historical synthetic test execution was blocked by Windows `AuthorizationManager` before the driver started (0 cases executed). That prior failure is retained; this release neither bypasses system execution policies nor provides a runtime certificate.
- **No Client Management:** The script does not automatically register or activate client applications or manage Python virtual environments. `-Output` can overwrite any explicitly selected file; it does not merge or automatically discover a client configuration. Python dependencies and environment availability remain the operator's responsibility.

## This source release

First-party helper source is distributed under the project’s [Apache-2.0 license](../LICENSE). The script bytes are unchanged from the existing reviewed candidate. A non-executing PowerShell 7.5.2 `ParseInput` check reported zero syntax errors for these bytes; this is not a Windows PowerShell 5.1 parse or runtime result. No script, native test driver, client configuration, MCP transport or model was run for this release. The old authorization refusal was not retried, and no security setting or execution policy was changed.
