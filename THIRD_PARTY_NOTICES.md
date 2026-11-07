# Third-Party Notices

Updated: 2026-08-05 | Codex (GPT-5.6)

Question Research POC is independently written research orchestration code. It
does not vendor the source of the projects listed below.

## Python Packages

| Project | Reviewed revision or constraint | License | Integration |
| --- | --- | --- | --- |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | `>=4.23,<5`; reviewed source `81f7a761cbaca107d3d261c1288155655b98ba08` | MIT | Required Draft 2020-12 validation for `research-output.v1` |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | optional `mcp>=1.0.0`; reviewed source `74a242ae7f52aee21cce7128a54ae8522c2f7c50` | MIT | Optional MCP-compatible server entrypoint |
| [pytest](https://github.com/pytest-dev/pytest) | test extra `>=8.2,<10` | MIT | Offline automated test runner; not a runtime dependency |

The package distributions provide their complete license texts. Their licenses
do not replace this project's Apache-2.0 license.

## External Tool Boundaries

The following tools are invoked only when separately installed and configured.
No source, credentials, browser profiles, archives, service data, or generated
research records from these tools are included in this repository.

| Project | Boundary |
| --- | --- |
| `ai-research-workflow` | Apache-2.0 external integration; install and configure it separately |
| `model-provider-gateway` | AGPL-3.0 external optional runtime; no source is vendored |
| `web-content-fetcher` | Separate Apache-2.0 package or sibling checkout for webpage acquisition |
| `video-knowledge-pipeline` | Separate local CLI for video processing |

Each external tool remains governed by its own license and runtime terms.
