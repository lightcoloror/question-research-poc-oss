# Security Policy

## Reporting A Vulnerability

Do not put credentials, browser profiles, cookies, private research material,
permissioned URLs, or captured page contents in a public issue.

Use GitHub Private Vulnerability Reporting when it is enabled. Otherwise,
contact the repository maintainer privately through GitHub with a minimal,
redacted reproduction. Never include a real token, cookie, provider session,
private URL, or personal research record.

## Local Data Boundary

Research projects and bridge artifacts are local data, not repository assets.
Keep `.research-question/`, `.local/`, provider/browser profiles, tool runs,
databases, logs, fetched content, and exported knowledge-base material outside
Git. Configure sibling tools with environment variables or explicit CLI
options; do not commit machine-specific paths or credentials.

The project must not bypass login, CAPTCHA, paywalls, access controls, or human
review gates. Candidate evidence and AI synthesis must not be represented as
verified facts.

## Release Checks

Before a public release or visibility change:

1. Run the full offline test suite and package build.
2. Run redacted secret scans against reachable history and the release archive.
3. Run `scripts/audit_release.py` against the staged release surface and archive.
4. Confirm ignored profiles, logs, PIDs, databases, research projects, and
   knowledge-base exports are not tracked.
5. Verify that all fixtures are synthetic and all final-answer gates fail closed.
