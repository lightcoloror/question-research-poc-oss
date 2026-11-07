from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any


SYNC_SAFETY_SCHEMA = "question_research_sync_safety.v1"

PROTECTED_PATTERNS = [
    "projects/**",
    "emergency-backups/**",
    ".research-question/**",
    ".local/**",
    "logs/**",
    "tool-runs/**",
    "state/tool-runs/**",
    "external-researcher-inbox/**",
    "provider-profiles/**",
    "browser-profiles/**",
    ".tmp-*.log",
    "web-*.log",
    "*.log",
    "*.sqlite",
    "*.db",
    "*.env",
]

SOURCE_PATTERNS = [
    "src/**",
    "tests/**",
    "web/**",
    "docs/**",
    "scripts/**",
    "config/**",
    "AGENT_DISCOVERY.md",
    "README.md",
    "MIGRATION.md",
    "pyproject.toml",
    ".gitignore",
]


def audit_sync_safety(repo: str | Path | None = None) -> dict[str, Any]:
    repo_root = Path(repo or Path.cwd()).resolve()
    status = _git(repo_root, ["status", "--short", "--branch"])
    remotes = _git(repo_root, ["remote", "-v"])
    diff_stat = _git(repo_root, ["diff", "--stat"])
    rows = _parse_status(status["stdout"])
    protected = [_classify(row, protected=True) for row in rows if _matches_any(row["path"], PROTECTED_PATTERNS)]
    source_candidates = [
        _classify(row, protected=False)
        for row in rows
        if _matches_any(row["path"], SOURCE_PATTERNS) and not _matches_any(row["path"], PROTECTED_PATTERNS)
    ]
    unknown = [
        _classify(row, protected=True, reason="Not recognized as source/config/docs; inspect before staging.")
        for row in rows
        if not _matches_any(row["path"], PROTECTED_PATTERNS) and not _matches_any(row["path"], SOURCE_PATTERNS)
    ]
    origin_present = any(line.startswith("origin") for line in remotes["stdout"].splitlines())
    return {
        "ok": True,
        "schema": SYNC_SAFETY_SCHEMA,
        "repo": str(repo_root),
        "branch": _branch_from_status(status["stdout"]),
        "dirty": bool(rows),
        "git": {
            "status_short": status["stdout"].splitlines(),
            "remote_v": remotes["stdout"].splitlines(),
            "diff_stat": diff_stat["stdout"].splitlines(),
            "errors": [item for item in [status["stderr"], remotes["stderr"], diff_stat["stderr"]] if item],
        },
        "counts": {
            "changed": len(rows),
            "source_candidates": len(source_candidates),
            "protected": len(protected),
            "needs_manual_classification": len(unknown),
        },
        "source_candidates": source_candidates,
        "protected_material": protected,
        "needs_manual_classification": unknown,
        "github_origin_advice": {
            "origin_present": origin_present,
            "recommended_repo_name": "question-research-poc",
            "recommended_visibility": "private-first",
            "reason": "This controller has useful source code, but local research projects and provider/browser artifacts must stay out of GitHub by default.",
            "before_first_sync": [
                "Commit only reviewed source/config/docs/test files.",
                "Keep projects/, emergency-backups/, runtime logs, provider profiles, API keys, login state, and source-restricted research artifacts untracked.",
                "Run audit-sync-safety and full regression checks immediately before staging.",
            ],
        },
        "operator_boundary": [
            "This audit is read-only; it does not stage, commit, create remotes, or push.",
            "projects/ is treated as local real research data by default.",
            "API keys, tokens, login state, and source-restricted content must not be committed.",
        ],
        "next_actions": _next_actions(origin_present, protected, unknown),
    }


def _git(repo_root: Path, args: list[str]) -> dict[str, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc)}
    return {"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def _parse_status(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line or line.startswith("## "):
            continue
        code = line[:2].strip() or "?"
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        rows.append({"status": code, "path": path.replace("\\", "/")})
    return rows


def _branch_from_status(text: str) -> str:
    first = next((line for line in text.splitlines() if line.startswith("## ")), "")
    return first[3:] if first else ""


def _matches_any(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) or normalized == pattern.rstrip("/**") for pattern in patterns)


def _classify(row: dict[str, str], *, protected: bool, reason: str | None = None) -> dict[str, str | bool]:
    return {
        "path": row["path"],
        "status": row["status"],
        "protected": protected,
        "reason": reason or ("Local artifact or sensitive-adjacent material; do not stage by default." if protected else "Source/config/docs candidate; still inspect diff before staging."),
    }


def _next_actions(origin_present: bool, protected: list[dict[str, Any]], unknown: list[dict[str, Any]]) -> list[str]:
    actions = []
    if protected:
        actions.append("Add or verify .gitignore coverage for protected local artifacts before any GitHub sync.")
    if unknown:
        actions.append("Manually classify unknown changed paths before staging.")
    if not origin_present:
        actions.append("If syncing to GitHub, create a private-first origin only after protected paths are excluded.")
    actions.append("Stage explicit source/config/docs files only; do not use broad git add .")
    return actions
