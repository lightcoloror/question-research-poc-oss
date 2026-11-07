from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FORBIDDEN_PARTS = {
    ".local",
    ".research-question",
    "browser-profile",
    "browser-profiles",
    "external-researcher-inbox",
    "logs",
    "model-assist-receipts",
    "provider-profiles",
    "projects",
    "tool-runs",
}
FORBIDDEN_SUFFIXES = {".db", ".log", ".pid", ".sqlite", ".sqlite3"}
TEXT_SUFFIXES = {
    "",
    ".cmd",
    ".css",
    ".env",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
PORTABLE_SURFACE = {"AGENT_DISCOVERY.md", "MIGRATION.md", "README.md", "config", "scripts", "src"}
PRIVATE_PATH_PATTERNS = {
    "windows_user_home": re.compile(r"(?i)[a-z]:[\\/]users[\\/](?!<user>|example)"),
    "syncthing_vault": re.compile(r"(?i)d:[\\/]used by syncthing"),
    "permission_url": re.compile(r"(?i)https?://[^\s\]\)]+(?:[?&](?:access_token|auth|key|sig|signature|token)=)"),
}
WORKSPACE_PATTERN = re.compile(r"(?i)d:[\\/]used-by-codex")


def audit(root: Path) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    files = sorted(path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts)
    for path in files:
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        lowered_parts = {part.lower() for part in relative.parts}
        if lowered_parts & FORBIDDEN_PARTS or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append({"code": "forbidden_release_path", "path": relative_text})
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for code, pattern in PRIVATE_PATH_PATTERNS.items():
            if pattern.search(text):
                findings.append({"code": code, "path": relative_text})
        top = relative.parts[0] if relative.parts else ""
        if top in PORTABLE_SURFACE and WORKSPACE_PATTERN.search(text):
            findings.append({"code": "hardcoded_workspace_path", "path": relative_text})
    return {
        "schema": "question-research-release-audit.v1",
        "root": str(root),
        "files_scanned": len(files),
        "status": "pass" if not findings else "blocked",
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed privacy and path audit for a QRP release surface.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
