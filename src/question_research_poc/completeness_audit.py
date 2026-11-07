from __future__ import annotations

from pathlib import Path
from typing import Any

from .orchestrator import list_records
from .review_state import build_review_queue, build_workflow_payload


def audit_research_completeness(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    if not (project_root / "research.json").exists():
        return {
            "ok": True,
            "schema": "question_research_completeness_audit.v1",
            "root": str(project_root),
            "ready_for_answer": False,
            "blocking_gates": ["project_not_initialized"],
            "warnings": [],
            "next_actions": ["先创建研究项目。"],
            "coverage": {},
            "items": [],
            "human_review_required": True,
        }

    sources = list_records(project_root, "sources")
    claims = list_records(project_root, "claims")
    evidence = list_records(project_root, "evidence")
    reviews = list_records(project_root, "reviews")
    workflow = build_workflow_payload(project_root)
    review_queue = build_review_queue(project_root)

    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(str(item.get("claim_id", "")), []).append(item)
    sources_by_id = {str(source.get("id", "")): source for source in sources}

    blockers: list[str] = []
    warnings: list[str] = []
    items: list[dict[str, Any]] = []

    if not sources:
        _add_blocker(blockers, items, "no_sources", "还没有来源。", "导入搜索结果、网页正文、视频知识包或手动添加来源。")
    if len({str(source.get("source_type", "unknown")) for source in sources}) < 2 and len(sources) < 3:
        warnings.append("来源数量或类型偏少，容易形成单一来源偏差。")
        items.append(_item("source_diversity", "warning", "来源多样性不足", "至少补充不同类型或不同渠道的来源。"))

    unknown_sources = [source for source in sources if str(source.get("quality", "unknown")) == "unknown"]
    if unknown_sources:
        _add_blocker(blockers, items, "unknown_source_quality", f"{len(unknown_sources)} 个来源还没有质量标注。", "在审核队列中标注 good / mixed / poor。", records=unknown_sources)

    poor_source_evidence = [
        item
        for item in evidence
        if str(item.get("status", "candidate")) != "rejected"
        and str(sources_by_id.get(str(item.get("source_id", "")), {}).get("quality", "")) == "poor"
    ]
    if poor_source_evidence:
        _add_blocker(blockers, items, "poor_source_evidence", f"{len(poor_source_evidence)} 条证据来自低质量来源。", "人工确认只能作为线索，或拒绝对应证据。", records=poor_source_evidence)

    if not claims:
        _add_blocker(blockers, items, "no_claims", "还没有主张或子问题。", "先生成研究计划或手动添加待验证主张。")
    for claim in claims:
        claim_id = str(claim.get("id", ""))
        rows = evidence_by_claim.get(claim_id, [])
        active_rows = [row for row in rows if str(row.get("status", "candidate")) != "rejected"]
        if not active_rows:
            _add_blocker(blockers, items, "claim_without_evidence", str(claim.get("text", "")), "给这个主张补充证据。", records=[claim])
        if not any(str(row.get("relation", "")) in {"contradicts", "context"} for row in rows):
            _add_warning(warnings, items, "missing_counter_evidence", str(claim.get("text", "")), "建议补充反证、上下文证据或反证搜索记录。", records=[claim])
        if not any(str(row.get("status", "")) == "verified" and str(row.get("relation", "")) == "supports" for row in active_rows):
            _add_blocker(blockers, items, "claim_without_verified_evidence", str(claim.get("text", "")), "至少通过一条支持证据。", records=[claim])

    candidate_evidence = [item for item in evidence if str(item.get("status", "candidate")) == "candidate"]
    if candidate_evidence:
        _add_blocker(blockers, items, "candidate_evidence_not_reviewed", f"{len(candidate_evidence)} 条候选证据未审核。", "在审核队列中通过或拒绝候选证据。", records=candidate_evidence)

    unreviewed_video_sources = [source for source in sources if _is_video_source(source) and str(source.get("quality", "unknown")) == "unknown"]
    if unreviewed_video_sources:
        _add_blocker(blockers, items, "imported_video_material_not_reviewed", f"{len(unreviewed_video_sources)} 个视频材料未审核来源质量。", "视频知识包只能作为候选材料，需人工确认来源质量和证据。", records=unreviewed_video_sources)

    draft_path = project_root / "notes" / "answer-draft.md"
    gate_audit = workflow.get("gate_audit") if isinstance(workflow, dict) else {}
    gates_pass = bool(gate_audit.get("ok")) if isinstance(gate_audit, dict) else False
    if draft_path.exists() and not gates_pass:
        warnings.append("已存在阶段性草稿，但 Gate 尚未全部通过；不能当最终答案发布。")
        items.append(_item("draft_before_gate_pass", "warning", str(draft_path), "先处理阻塞 Gate，再输出最终答案。"))

    if not reviews:
        warnings.append("还没有任何人工审核记录。")
        items.append(_item("no_human_reviews", "warning", "缺少人工审核记录", "至少完成来源质量或证据审核。"))

    required_review_queue = [item for item in review_queue if str(item.get("item_type", "")) != "missing_counter_evidence"]
    coverage = {
        "source_count": len(sources),
        "source_types": sorted({str(source.get("source_type", "unknown")) for source in sources}),
        "unknown_source_quality": len(unknown_sources),
        "claim_count": len(claims),
        "claims_with_evidence": sum(1 for claim in claims if any(str(row.get("status", "candidate")) != "rejected" for row in evidence_by_claim.get(str(claim.get("id", "")), []))),
        "claims_with_verified_evidence": sum(1 for claim in claims if any(str(row.get("status", "")) == "verified" for row in evidence_by_claim.get(str(claim.get("id", "")), []))),
        "claims_with_verified_support_evidence": sum(1 for claim in claims if any(str(row.get("status", "")) == "verified" and str(row.get("relation", "")) == "supports" for row in evidence_by_claim.get(str(claim.get("id", "")), []))),
        "claims_with_counter_or_context": sum(1 for claim in claims if any(str(row.get("relation", "")) in {"contradicts", "context"} for row in evidence_by_claim.get(str(claim.get("id", "")), []))),
        "candidate_evidence": len(candidate_evidence),
        "poor_source_evidence": len(poor_source_evidence),
        "review_queue_count": len(review_queue),
        "required_review_queue_count": len(required_review_queue),
        "human_review_count": len(reviews),
        "draft_exists": draft_path.exists(),
        "gate_audit_passed": gates_pass,
    }

    return {
        "ok": True,
        "schema": "question_research_completeness_audit.v1",
        "root": str(project_root),
        "ready_for_answer": not blockers and bool(claims) and bool(sources),
        "blocking_gates": sorted(set(blockers)),
        "warnings": warnings,
        "next_actions": _next_actions_from_blockers(blockers) or _next_actions_from_warnings(items) or ["可以生成阶段性答案；发布前仍建议导出研究包人工复核。"],
        "coverage": coverage,
        "items": items,
        "human_review_required": bool(blockers or required_review_queue),
    }


def _add_blocker(blockers: list[str], items: list[dict[str, Any]], blocker: str, title: str, action: str, *, records: list[dict[str, Any]] | None = None) -> None:
    blockers.append(blocker)
    items.append(_item(blocker, "blocker", title, action, records=records or []))


def _add_warning(warnings: list[str], items: list[dict[str, Any]], warning: str, title: str, action: str, *, records: list[dict[str, Any]] | None = None) -> None:
    warnings.append(warning)
    items.append(_item(warning, "warning", title, action, records=records or []))


def _item(item_type: str, severity: str, title: str, action: str, *, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "item_type": item_type,
        "severity": severity,
        "title": title,
        "action": action,
        "record_count": len(records or []),
        "records": _record_refs(records or []),
    }


def _record_refs(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for record in records[:12]:
        record_id = str(record.get("id") or record.get("claim_id") or record.get("source_id") or "")
        title = str(record.get("title") or record.get("text") or record.get("quote_or_note") or record_id)
        refs.append({"id": record_id, "title": title[:240]})
    return refs


def _is_video_source(source: dict[str, Any]) -> bool:
    source_type = str(source.get("source_type", "")).lower()
    text = " ".join(str(source.get(key, "")) for key in ("title", "path", "url", "notes")).lower()
    return source_type == "video" or "video-knowledge-pipeline" in text or "webui-bundle" in text


def _next_actions_from_blockers(blockers: list[str]) -> list[str]:
    mapping = {
        "no_sources": "先通过资料收件箱、搜索桥接、网页抓取或视频知识包导入来源。",
        "unknown_source_quality": "优先处理审核队列里的来源质量项。",
        "no_claims": "先生成研究计划并写入主张。",
        "claim_without_evidence": "给无证据主张补充网页、文档或视频材料证据。",
        "claim_without_verified_evidence": "审核候选证据，至少让每个核心主张有 verified evidence。",
        "missing_counter_evidence": "为核心主张补充 contradicts/context 证据或反证搜索记录。",
        "candidate_evidence_not_reviewed": "处理候选证据审核队列。",
        "poor_source_evidence": "人工复核低质量来源产生的证据。",
        "imported_video_material_not_reviewed": "复核视频知识包导入的来源质量和候选证据。",
    }
    return [mapping[key] for key in mapping if key in set(blockers)]


def _next_actions_from_warnings(items: list[dict[str, Any]]) -> list[str]:
    warning_actions = []
    for item in items:
        if item.get("severity") == "warning" and item.get("item_type") == "missing_counter_evidence":
            warning_actions.append("建议为核心主张补充 contradicts/context 证据或反证搜索记录；这不是最终答案硬阻塞。")
    return warning_actions
