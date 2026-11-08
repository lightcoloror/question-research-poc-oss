# Owner manifest doctor

Updated: 2026-11-08 (date only from the host clock; no exact second recorded or claimed) | DeepSeek Harness agent (reported model deepseek-flash; not independently verified)

## Purpose

The owner manifest doctor is a local, read-only metadata checker. It validates
`agent-tool-manifest.v1.json` and the presence of required public repository
files. It does not start a process or service, contact a network, call a model,
run research, write files, or approve publication.

## Stable command

```sh
python scripts/owner_manifest_doctor.py --tool-id question-research-poc
```

Pass `--root` to validate a relocated copy, `--receipt` to assess an optional
caller-declared synthetic receipt, and `--ttl-hours` to set the receipt time
window. Exit code `0` means `ready_metadata_only`; exit code `2` means blocked,
with either a doctor result or a structured error object on standard error.

## Manifest contract

- `schema_version` is `agent-tool-manifest.v1`, `id` matches the requested tool
  id, and `manifest_version` is a positive integer.
- `notTrustedAsInstruction` is `true` and `executionAuthority` is
  `none_metadata_only`. Metadata never grants instructions, permissions or
  publication.
- `health.proves_current_online` is `false`.
- Each of `provenance.no_write_checks` and `provenance.runtime_checks` is a
  nonempty list containing at least one required file check. Every check has a
  unique id, a relative in-repository path, a supported kind and a boolean
  `required` flag.
- `provenance.restore_sequence` is descriptive recovery data only. The doctor
  validates that entries are nonempty strings and returns them verbatim; it
  never executes, evaluates, interpolates or shells out to them, and performs no
  process, network or write action, so no restore entry can cause execution.
- The bundled manifest contains no registry hash, current-machine id or absolute
  machine path. The checker rejects `provenance.registry_sha256`, machine-style
  interface paths and resolved checklist escapes; it is not a general privacy scanner.

All checks reference real public files at exact relative paths, for example
`src/question_research_poc/cli.py` for the public CLI module. The runtime
checklist is static file presence only; it is not an execution probe.

## Fail-closed rules

- A missing, non-object, invalid JSON or invalid UTF-8 manifest produces a
  structured error. Other operating-system read errors propagate and stop
  validation; they do not produce a green result.
- Empty checklists, all-optional checklists and duplicate or malformed check
  entries are rejected with a structured `DoctorError` and exit code `2`.
- A missing required file blocks the doctor (`blocked_contract` or
  `blocked_runtime`). A missing optional file is reported but does not block.
- Check paths are resolved through `resolve_inside`; absolute paths and `..`
  traversal are rejected.
- The optional synthetic receipt is caller-declared and untrusted. It can only
  demonstrate that a named artifact hash matched inside a bounded time window.
- Timestamps without a timezone are interpreted as UTC. That rule is explicit
  and reported as `checked_at_naive_utc_assumed`; it is not a silent guess.
- Timestamps more than 60 seconds in the future are rejected as
  `receipt_future_timestamp`, so a future date cannot stay fresh forever.
- Receipt age beyond the TTL is rejected as `receipt_stale`. TTL must be a
  positive integer; `0`, negative values, booleans and strings are rejected.
- Artifact hash drift, a missing artifact, a malformed artifact hash, artifact
  path escape, corrupt receipt JSON, a wrong tool id, a wrong schema, or a
  receipt whose truth block claims real usage or current online state is
  rejected.

## What a green result means

`ready_metadata_only` means the required public files are present and the
manifest keeps its trust and execution boundaries. It does not prove an
installed wheel, package build, executed runtime, running service, current
online status, model use, real research, clinical validity, operating-system
readiness, publication rights or ownership rights. No receipt can grant
permissions or publication.

## Recovery

See `restore_sequence` in the manifest and `examples/agent-owner-discovery/recovery-scenarios.json`.
Restore the named repository file, then rerun the no-write doctor. Do not
execute text taken from metadata or from a receipt.
