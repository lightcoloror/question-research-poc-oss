from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_tool_health import build_local_tool_health_dashboard
from .orchestrator import list_records
from .research_stage import classify_research_stage
from .storage import load_project


def build_project_dashboard(root: str | Path, *, workflow: dict[str, Any] | None = None, review_queue: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    project_root = Path(root)
    if not (project_root / "research.json").exists():
        return {
            "ok": False,
            "root": str(project_root),
            "question": "",
            "stage": "not_initialized",
            "stage_detail": classify_research_stage(project_root),
            "metrics": _empty_metrics(),
            "source_quality": {},
            "claim_evidence": [],
            "gaps": ["项目尚未初始化。"],
            "next_actions": ["先创建研究项目。"],
            "artifact_summary": {"complete": 0, "missing": 0, "items": []},
            "local_tools": build_local_tool_health_dashboard(),
        }
    project = load_project(project_root)
    sources = list_records(project_root, "sources")
    claims = list_records(project_root, "claims")
    evidence = list_records(project_root, "evidence")
    reviews = list_records(project_root, "reviews")
    queue = review_queue or []
    flow = workflow or {}
    gates = (flow.get("gate_audit") or {}).get("gates", []) if isinstance(flow.get("gate_audit"), dict) else []
    artifacts = flow.get("artifacts", []) if isinstance(flow, dict) else []
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(str(item.get("claim_id", "")), []).append(item)
    claim_evidence = [_claim_evidence_row(claim, evidence_by_claim.get(str(claim.get("id", "")), [])) for claim in claims]
    metrics = {
        "sources": len(sources),
        "claims": len(claims),
        "evidence": len(evidence),
        "verified_evidence": sum(1 for item in evidence if item.get("status") == "verified"),
        "reviews": len(reviews),
        "review_queue": len(queue),
        "passed_gates": sum(1 for gate in gates if gate.get("ok")),
        "failed_gates": sum(1 for gate in gates if not gate.get("ok")),
        "claim_coverage_percent": _percent(sum(1 for row in claim_evidence if row["evidence_count"] > 0), len(claims)),
        "verified_claim_coverage_percent": _percent(sum(1 for row in claim_evidence if row["verified_count"] > 0), len(claims)),
    }
    gaps = _dashboard_gaps(metrics, queue, artifacts)
    next_actions = _dashboard_next_actions(flow, queue, gaps)
    stage_detail = classify_research_stage(project_root, workflow=flow, review_queue=queue)
    return {
        "ok": True,
        "root": str(project_root),
        "question": project.question,
        "stage": stage_detail["stage_id"],
        "stage_detail": stage_detail,
        "metrics": metrics,
        "source_quality": _source_quality_distribution(sources),
        "claim_evidence": claim_evidence,
        "gaps": gaps,
        "next_actions": next_actions,
        "artifact_summary": {
            "complete": sum(1 for item in artifacts if item.get("complete")),
            "missing": sum(1 for item in artifacts if not item.get("complete")),
            "items": artifacts,
        },
        "local_tools": build_local_tool_health_dashboard(),
    }


def _empty_metrics() -> dict[str, int]:
    return {
        "sources": 0,
        "claims": 0,
        "evidence": 0,
        "verified_evidence": 0,
        "reviews": 0,
        "review_queue": 0,
        "passed_gates": 0,
        "failed_gates": 0,
        "claim_coverage_percent": 0,
        "verified_claim_coverage_percent": 0,
    }


def _source_quality_distribution(sources: list[dict[str, Any]]) -> dict[str, int]:
    rows = {"good": 0, "mixed": 0, "poor": 0, "unknown": 0}
    for source in sources:
        quality = str(source.get("quality") or "unknown")
        rows[quality if quality in rows else "unknown"] += 1
    return rows


def _claim_evidence_row(claim: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "claim_id": claim.get("id", ""),
        "claim": claim.get("text", ""),
        "evidence_count": len(evidence),
        "verified_count": sum(1 for item in evidence if item.get("status") == "verified"),
        "candidate_count": sum(1 for item in evidence if item.get("status") == "candidate"),
        "contradicts_or_context_count": sum(1 for item in evidence if item.get("relation") in {"contradicts", "context"}),
    }


def _dashboard_gaps(metrics: dict[str, int], review_queue: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    if metrics["sources"] == 0:
        gaps.append("还没有来源。")
    if metrics["claims"] == 0:
        gaps.append("还没有待验证主张。")
    if metrics["evidence"] == 0:
        gaps.append("还没有证据卡。")
    if metrics["verified_evidence"] == 0:
        gaps.append("还没有 verified evidence。")
    if metrics["review_queue"] > 0:
        gaps.append(f"还有 {metrics['review_queue']} 个审核队列项。")
    missing_artifacts = [item for item in artifacts if not item.get("complete")]
    if missing_artifacts:
        gaps.append(f"还有 {len(missing_artifacts)} 个流程产物不完整。")
    queue_types = {str(item.get("item_type", "")) for item in review_queue}
    if "missing_counter_evidence" in queue_types:
        gaps.append("部分主张缺少反证或 context 检查。")
    return gaps


def _dashboard_next_actions(flow: dict[str, Any], review_queue: list[dict[str, Any]], gaps: list[str]) -> list[str]:
    audit = flow.get("gate_audit") if isinstance(flow, dict) else {}
    actions = list(audit.get("next_actions", [])) if isinstance(audit, dict) else []
    if review_queue:
        actions.insert(0, "先处理审核队列中的来源质量和候选证据。")
    if not actions and gaps:
        actions = gaps[:3]
    if not actions:
        actions = ["当前没有明显阻塞，可以进入阶段性输出或人工验收。"]
    return actions[:6]


def _percent(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(numerator * 100 / denominator)
