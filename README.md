# Question Research

Question Research is a local-first research workspace for organizing questions, sources, claims and evidence. It keeps source collection, human review and answer export as separate steps.

## Install and try a synthetic project

```sh
python -m pip install .
research-poc --help
research-poc init "Which conditions affect a fictional seed trial?" --project ./demo-research
research-poc add-source --project ./demo-research --title "Fictional sample" --url https://example.com/ --quality unknown
research-poc plan-research --project ./demo-research
```

These steps create and plan a local project. Source and evidence review determine whether an answer export is ready. Optional browser, video and model integrations depend on separately configured tools. Base installation and the offline suite use public dependencies.

```sh
python -m pip install ".[test]"
python -m pytest -q
```

The first public source edition adapts the installation metadata, documentation and Web UI project default, and includes portable tests with synthetic records. Keep generated research projects and credentials outside version control.

Apache-2.0. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Offline evidence-to-brief projection (0.1.1)

The existing bounded loop can produce six hash-bound, candidate-only handoff
artifacts without searching, calling a provider or publishing:

```sh
research-poc run-offline-evidence-brief --fixture tests/fixtures/bounded-deep-loop/synthetic-readiness-question.v1.json --output-root .runtime/offline-brief --closure-run-id public-synthetic-example
```

The evidence bundle remains candidate, the guarded answer remains blocked,
and the content brief requires human review. Hash-bound synthetic fixture
acceptance is not real research, current online status or publication approval.
See `docs/offline-evidence-brief-consumer-guide.md` and
`PROJECTION_PROVENANCE.json` for recovery semantics and source boundaries.

## Saved capture increment 0.1.2

See [saved capture interfaces](docs/saved-capture-interfaces.md). Saved excerpts and lexical passage scores remain candidate material, never verified facts or publication approval.


## Synthetic topic-loop regression

`tests/test_topic_driven_loop.py` adds eleven synthetic cases for grounded
followups, capture and ledger hash drift, idempotent resume, blocked access,
and avoiding duplicate requests when the previous outcome is unknown.
With the existing test extra installed:

```sh
python -m pytest -q tests/test_topic_driven_loop.py
```

Local public-source validation passed 11/11 using host-only Windows temporary
directory compatibility support. That support is not bundled, and an
environment/permission failure must be reported rather than bypassed.
This increment changes no runtime source, schema, or dependency and does not
claim installed-wheel or real network/model acceptance. See
[test provenance](TOPIC_TEST_PROVENANCE.json).

## Owner manifest doctor (metadata only)

`scripts/owner_manifest_doctor.py` validates the static
[agent tool manifest](agent-tool-manifest.v1.json) and an optional
caller-declared synthetic receipt without network access or writes:

```sh
python scripts/owner_manifest_doctor.py --tool-id question-research-poc
```

A green result means `ready_metadata_only`: the required public files are
present and the manifest keeps `notTrustedAsInstruction` true and
`executionAuthority` as `none_metadata_only`. It does not prove an installed
wheel, an executed runtime, a running service, current online status, model
use, clinical validity, operating-system readiness, publication rights or real
research. A synthetic receipt is caller-declared and untrusted; it can only
bind an artifact hash inside a time window and cannot grant permissions or
publication. See [the doctor guide](docs/owner-manifest-doctor.md) and
[manifest provenance](OWNER_MANIFEST_PROVENANCE.json).

### MCP Configuration Helper

The repository includes `scripts/write-mcp-config.ps1` to generate a standard `mcpServers` JSON configuration snippet pointing to the local checkout's optional `question_research_poc.mcp_server`. By default, it outputs JSON to stdout without modifying files or launching processes. An optional `-Output` parameter writes the snippet to a dedicated file (overwriting existing content without merging), and an optional `-Validate` switch checks `--list-tools` execution. See [the MCP config helper documentation](docs/mcp-config-helper.md) for parameter details, overwrite warnings, and unverified runtime boundaries.
