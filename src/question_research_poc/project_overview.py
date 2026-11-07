from __future__ import annotations

from pathlib import Path
from typing import Any

from .dashboard import build_project_dashboard
from .orchestrator import list_records
from .review_state import build_review_queue, build_workflow_payload
from .storage import load_project


def build_project_overview(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    workflow = build_workflow_payload(project_root)
    review_queue = build_review_queue(project_root)
    dashboard = build_project_dashboard(project_root, workflow=workflow, review_queue=review_queue)
    if not (project_root / "research.json").exists():
        return {
            "ok": False,
            "schema": "question_research_project_overview.v1",
            "root": str(project_root),
            "question": "",
            "message": "project not initialized",
            "dashboard": dashboard,
        }
    project = load_project(project_root)
    sources = list_records(project_root, "sources")
    claims = list_records(project_root, "claims")
    evidence = list_records(project_root, "evidence")
    sources_by_id = {str(source.get("id", "")): source for source in sources}
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(str(item.get("claim_id", "")), []).append(item)
    return {
        "ok": True,
        "schema": "question_research_project_overview.v1",
        "root": str(project_root),
        "question": project.question,
        "project": {
            "id": project.id,
            "status": project.status,
            "created_at": project.created_at,
        },
        "stage": dashboard.get("stage_detail", {}),
        "metrics": dashboard.get("metrics", {}),
        "gate_summary": _gate_summary(workflow),
        "source_quality": dashboard.get("source_quality", {}),
        "claim_evidence": [_claim_overview(claim, evidence_by_claim.get(str(claim.get("id", "")), []), sources_by_id) for claim in claims],
        "gaps": dashboard.get("gaps", []),
        "next_actions": dashboard.get("next_actions", []),
        "important_artifacts": _important_artifacts(workflow),
        "review_queue": {
            "count": len(review_queue),
            "by_type": _counts_by_key(review_queue, "item_type"),
            "items": review_queue[:10],
        },
        "human_review_required": bool(review_queue),
    }


def _gate_summary(workflow: dict[str, Any]) -> dict[str, Any]:
    gate_audit = workflow.get("gate_audit", {}) if isinstance(workflow, dict) else {}
    gates = gate_audit.get("gates", []) if isinstance(gate_audit, dict) else []
    rows = [gate for gate in gates if isinstance(gate, dict)]
    failed = [gate for gate in rows if not gate.get("ok")]
    return {
        "has_gate_audit": bool(workflow.get("has_gate_audit")) if isinstance(workflow, dict) else False,
        "ok": bool(gate_audit.get("ok", False)) if isinstance(gate_audit, dict) else False,
        "passed": sum(1 for gate in rows if gate.get("ok")),
        "failed": len(failed),
        "next_gate": gate_audit.get("next_gate", "") if isinstance(gate_audit, dict) else "",
        "failed_gates": [
            {
                "id": str(gate.get("id", "")),
                "title": str(gate.get("title") or gate.get("description") or ""),
                "severity": str(gate.get("severity", "")),
                "current": gate.get("current", ""),
                "target": gate.get("target", ""),
            }
            for gate in failed[:8]
        ],
    }


def _claim_overview(claim: dict[str, Any], evidence: list[dict[str, Any]], sources_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    verified = [item for item in evidence if item.get("status") == "verified"]
    candidate = [item for item in evidence if item.get("status") == "candidate"]
    context = [item for item in evidence if item.get("relation") in {"contradicts", "context"}]
    return {
        "claim_id": claim.get("id", ""),
        "claim": claim.get("text", ""),
        "evidence_count": len(evidence),
        "verified_count": len(verified),
        "candidate_count": len(candidate),
        "contradicts_or_context_count": len(context),
        "coverage_status": _coverage_status(evidence, verified, context),
        "sources": sorted(
            {
                str(sources_by_id.get(str(item.get("source_id", "")), {}).get("title") or item.get("source_id", ""))
                for item in evidence
                if item.get("source_id")
            }
        ),
    }


def _coverage_status(evidence: list[dict[str, Any]], verified: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
    if not evidence:
        return "missing_evidence"
    if not verified:
        return "candidate_only"
    if not context:
        return "verified_without_counter_context"
    return "reviewable"


def _important_artifacts(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = workflow.get("artifacts", []) if isinstance(workflow, dict) else []
    rows = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        if item.get("id") in {"task_route", "research_plan", "gate_audit", "next_steps", "multi_perspective_review", "reader_persona_review"}:
            rows.append(
                {
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "complete": bool(item.get("complete")),
                    "markdown_path": item.get("markdown_path", ""),
                    "json_path": item.get("json_path", ""),
                }
            )
    return rows


def _counts_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts

