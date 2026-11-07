from __future__ import annotations

from pathlib import Path
from typing import Any

from .completeness_audit import audit_research_completeness
from .orchestrator import draft_answer
from .storage import load_project, write_json


FINAL_ANSWER_SCHEMA = "question_research_final_answer_export.v1"


def export_final_answer(root: str | Path, output_dir: str | Path | None = None, *, allow_incomplete: bool = False) -> dict[str, Any]:
    """Export a final-like answer only after deterministic completeness checks."""
    project_root = Path(root)
    project = load_project(project_root)
    audit = audit_research_completeness(project_root)
    ready = bool(audit.get("ready_for_answer"))
    output = Path(output_dir) if output_dir else project_root / "exports" / "final-answer"

    if not ready and not allow_incomplete:
        return {
            "ok": False,
            "schema": FINAL_ANSWER_SCHEMA,
            "root": str(project_root),
            "ready_for_answer": False,
            "blocked": True,
            "exported": False,
            "human_review_required": True,
            "error": "completeness_audit_blocked_final_answer",
            "blocking_gates": audit.get("blocking_gates", []),
            "next_actions": audit.get("next_actions", []),
            "audit": audit,
        }

    output.mkdir(parents=True, exist_ok=True)
    answer_path = output / "final-answer.md"
    audit_path = output / "completeness-audit.json"
    payload_path = output / "final-answer-export.json"
    markdown = _render_final_answer(project.question, draft_answer(project_root, include_candidate=allow_incomplete), audit, ready=ready, allow_incomplete=allow_incomplete)
    answer_path.write_text(markdown, encoding="utf-8")
    write_json(audit_path, audit)

    payload = {
        "ok": True,
        "schema": FINAL_ANSWER_SCHEMA,
        "root": str(project_root),
        "output_dir": str(output),
        "ready_for_answer": ready,
        "allow_incomplete": allow_incomplete,
        "blocked": False,
        "exported": True,
        "human_review_required": bool(not ready or audit.get("human_review_required")),
        "blocking_gates": audit.get("blocking_gates", []),
        "warnings": audit.get("warnings", []),
        "files": {
            "markdown": str(answer_path),
            "audit": str(audit_path),
            "json": str(payload_path),
        },
    }
    write_json(payload_path, payload)
    return payload


def _render_final_answer(question: str, answer: str, audit: dict[str, Any], *, ready: bool, allow_incomplete: bool) -> str:
    lines = [
        f"# 最终答案：{question}",
        "",
    ]
    if ready:
        lines.extend(["Status: ready_for_answer", ""])
    elif allow_incomplete:
        lines.extend(
            [
                "Status: incomplete_export",
                "",
                "> This output was exported with `allow_incomplete=true`. It is not a final publishable answer.",
                "",
                "## Blocking Gates",
                "",
            ]
        )
        for gate in audit.get("blocking_gates", []):
            lines.append(f"- `{gate}`")
        lines.extend(["", "## Required Next Actions", ""])
        for action in audit.get("next_actions", []):
            lines.append(f"- {action}")
        lines.append("")
    else:
        lines.extend(["Status: blocked", ""])
    lines.extend(["## Answer", "", answer.rstrip(), "", "## Completeness Snapshot", ""])
    lines.append(f"- ready_for_answer: `{str(ready).lower()}`")
    lines.append(f"- blocking_gates: {len(audit.get('blocking_gates', []))}")
    warnings = audit.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- `{warning}`")
    coverage = audit.get("coverage", {}) if isinstance(audit.get("coverage"), dict) else {}
    for key in ("source_count", "claim_count", "claims_with_verified_evidence", "candidate_evidence", "review_queue_count"):
        if key in coverage:
            lines.append(f"- {key}: {coverage.get(key)}")
    return "\n".join(lines).rstrip() + "\n"
