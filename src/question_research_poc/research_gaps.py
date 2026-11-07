from __future__ import annotations

from pathlib import Path
from typing import Any

from .completeness_audit import audit_research_completeness
from .orchestrator import list_records
from .storage import load_project


ACTIONABLE_STATUS = "actionable_search"
REVIEW_STATUS = "needs_review"


def analyze_research_gaps(
    root: str | Path,
    *,
    query: str | None = None,
    ai_quality: dict[str, Any] | None = None,
    deepen_suggestions: dict[str, Any] | None = None,
    max_queries_per_round: int = 3,
) -> dict[str, Any]:
    project = load_project(root)
    topic = str(query or project.question)
    sources = list_records(root, "sources")
    claims = list_records(root, "claims")
    evidence = list_records(root, "evidence")
    audit = audit_research_completeness(root)
    gaps = _dedupe_gaps(
        [
            *_source_gaps(topic, sources),
            *_claim_gaps(topic, claims, evidence, ai_quality or {}, deepen_suggestions or {}),
            *_evidence_gaps(claims, evidence, ai_quality or {}),
            *_counter_evidence_gaps(claims, evidence),
            *_freshness_gaps(topic, claims, sources),
            *_review_gaps(sources, evidence, audit),
        ]
    )
    queries = plan_followup_queries(gaps, max_queries=max_queries_per_round)
    return {
        "ok": True,
        "schema": "question_research_gap_analysis.v1",
        "root": str(Path(root)),
        "query": topic,
        "status": "has_actionable_gaps" if queries else ("needs_review_only" if any(gap["status"] == REVIEW_STATUS for gap in gaps) else "no_gaps"),
        "gaps": gaps,
        "actionable_queries": queries,
        "skipped_queries": _skipped_queries(gaps, queries),
        "audit": audit,
        "human_review_required": bool(audit.get("human_review_required") or any(gap["status"] == REVIEW_STATUS for gap in gaps)),
    }


def plan_followup_queries(gaps: list[dict[str, Any]], *, max_queries: int = 3) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    actionable = [gap for gap in gaps if gap.get("status") == ACTIONABLE_STATUS]
    actionable.sort(key=lambda gap: (_priority_rank(str(gap.get("priority") or "P2")), str(gap.get("id") or "")))
    for gap in actionable:
        for query in gap.get("suggested_queries") or []:
            normalized = _norm(query)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(
                {
                    "query": str(query),
                    "gap_id": gap.get("id", ""),
                    "gap_type": gap.get("type", ""),
                    "priority": gap.get("priority", "P2"),
                    "reason": gap.get("title", ""),
                }
            )
            if len(output) >= max_queries:
                return output
    return output


def _source_gaps(topic: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sources:
        return [
            _gap(
                "source_bucket_gap",
                "P1",
                ACTIONABLE_STATUS,
                "还没有任何来源",
                "第一轮需要至少导入候选来源。",
                [topic],
                record_id="sources",
            )
        ]
    gaps: list[dict[str, Any]] = []
    source_text = " ".join(
        f"{source.get('title', '')} {source.get('url', '')} {source.get('notes', '')}".lower()
        for source in sources
    )
    if _looks_needing_official(topic) and not any(token in source_text for token in ("official", "官网", "docs", "documentation", "监管", "公告", "github.com")):
        gaps.append(
            _gap(
                "source_bucket_gap",
                "P1",
                ACTIONABLE_STATUS,
                "缺少官方或一手来源",
                "需要官方文档、监管公告、项目仓库或原始出处，避免只靠二手材料。",
                [f"{topic} official documentation", f"{topic} site:gov OR site:edu OR site:org"],
                record_id="official_source",
            )
        )
    if len(sources) < 3:
        gaps.append(
            _gap(
                "source_bucket_gap",
                "P2",
                ACTIONABLE_STATUS,
                "来源数量偏少",
                "少于 3 个来源时容易形成单一来源偏差。",
                [f"{topic} independent source", f"{topic} counter evidence"],
                record_id="source_diversity",
            )
        )
    return gaps


def _claim_gaps(
    topic: str,
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    ai_quality: dict[str, Any],
    deepen_suggestions: dict[str, Any],
) -> list[dict[str, Any]]:
    if not claims:
        return [
            _gap(
                "claim_gap",
                "P1",
                ACTIONABLE_STATUS,
                "还没有可验证主张",
                "需要先通过机器 claim extraction 或人工拆解生成候选主张。",
                [f"{topic} key facts evidence", f"{topic} claims verification"],
                record_id="claims",
            )
        ]
    evidence_by_claim = _evidence_by_claim(evidence)
    suggestions_by_claim = _suggestions_by_claim(deepen_suggestions)
    quality_by_claim = _quality_by_claim(ai_quality)
    gaps: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = str(claim.get("id") or "")
        text = str(claim.get("text") or "")
        notes = str(claim.get("notes") or "")
        verdict = _claim_verdict(claim, quality_by_claim.get(claim_id, {}))
        quality = quality_by_claim.get(claim_id, {})
        suggested = suggestions_by_claim.get(claim_id) or suggestions_by_claim.get(text) or []
        if verdict in {"not_found", "partial"}:
            gaps.append(
                _gap(
                    "claim_gap",
                    "P1",
                    ACTIONABLE_STATUS,
                    f"主张仍是 {verdict}",
                    text,
                    suggested or [f"{text} evidence", f"{text} official source"],
                    record_id=claim_id,
                )
            )
        if "risk_level: high" in notes or quality.get("risk_level") == "high":
            source_diversity = int(quality.get("source_diversity") or len({row.get("source_id") for row in evidence_by_claim.get(claim_id, []) if row.get("source_id")}))
            if source_diversity < 2:
                gaps.append(
                    _gap(
                        "claim_gap",
                        "P0",
                        ACTIONABLE_STATUS,
                        "高风险主张缺少第二独立来源",
                        text,
                        suggested or [f"{text} independent source", f"{text} contradiction"],
                        record_id=claim_id,
                    )
                )
    return gaps


def _evidence_gaps(claims: list[dict[str, Any]], evidence: list[dict[str, Any]], ai_quality: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_by_claim = _evidence_by_claim(evidence)
    quality_by_claim = _quality_by_claim(ai_quality)
    gaps: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = str(claim.get("id") or "")
        text = str(claim.get("text") or "")
        rows = evidence_by_claim.get(claim_id, [])
        quality = quality_by_claim.get(claim_id, {})
        weak_reasons = [str(item) for item in quality.get("weak_reasons") or []]
        if not rows:
            gaps.append(_gap("evidence_gap", "P1", ACTIONABLE_STATUS, "主张没有证据", text, [f"{text} source evidence"], record_id=claim_id))
        elif any(len(str(row.get("quote_or_note") or "")) < 40 for row in rows) or quality.get("evidence_strength") == "weak":
            gaps.append(
                _gap(
                    "evidence_gap",
                    "P2",
                    ACTIONABLE_STATUS,
                    "证据强度偏弱",
                    "; ".join(weak_reasons) or text,
                    [f"{text} detailed evidence", f"{text} primary source"],
                    record_id=claim_id,
                )
            )
    return gaps


def _counter_evidence_gaps(claims: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_by_claim = _evidence_by_claim(evidence)
    gaps: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = str(claim.get("id") or "")
        text = str(claim.get("text") or "")
        rows = evidence_by_claim.get(claim_id, [])
        if rows and not any(str(row.get("relation") or "") in {"contradicts", "context"} for row in rows):
            gaps.append(
                _gap(
                    "counter_evidence_gap",
                    "P2",
                    ACTIONABLE_STATUS,
                    "缺少反证或上下文证据",
                    text,
                    [f"{text} criticism", f"{text} limitation", f"{text} contradiction"],
                    record_id=claim_id,
                )
            )
    return gaps


def _freshness_gaps(topic: str, claims: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = " ".join([topic, *[str(claim.get("text") or "") for claim in claims]])
    if not _looks_freshness_sensitive(text):
        return []
    source_text = " ".join(str(source.get("title") or "") + " " + str(source.get("notes") or "") for source in sources)
    if "checked_at" in source_text or "published_at" in source_text or "2026" in source_text:
        return []
    return [
        _gap(
            "freshness_gap",
            "P0",
            ACTIONABLE_STATUS,
            "时效性事实缺少当前证据",
            "产品可售、资质有效、服务端口、价格、政策等事实需要当前证据。",
            [f"{topic} current status", f"{topic} 2026 official"],
            record_id="freshness",
        )
    ]


def _review_gaps(sources: list[dict[str, Any]], evidence: list[dict[str, Any]], audit: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    unknown_sources = [source for source in sources if str(source.get("quality") or "unknown") == "unknown"]
    if unknown_sources:
        gaps.append(
            _gap(
                "review_gap",
                "P2",
                REVIEW_STATUS,
                "来源质量未审核",
                f"{len(unknown_sources)} 个来源仍是 unknown。",
                [],
                record_id="unknown_source_quality",
            )
        )
    candidate_evidence = [row for row in evidence if str(row.get("status") or "candidate") == "candidate"]
    if candidate_evidence:
        gaps.append(
            _gap(
                "review_gap",
                "P2",
                REVIEW_STATUS,
                "候选证据未人工审核",
                f"{len(candidate_evidence)} 条 evidence 仍是 candidate。",
                [],
                record_id="candidate_evidence",
            )
        )
    for item in audit.get("items") or []:
        if item.get("item_type") == "poor_source_evidence":
            gaps.append(_gap("review_gap", "P1", REVIEW_STATUS, "低质量来源证据需人工处理", str(item.get("title") or ""), [], record_id="poor_source_evidence"))
    return gaps


def _gap(
    gap_type: str,
    priority: str,
    status: str,
    title: str,
    reason: str,
    queries: list[str],
    *,
    record_id: str,
) -> dict[str, Any]:
    return {
        "id": f"{gap_type}:{record_id}:{_norm(title)[:48]}",
        "type": gap_type,
        "priority": priority,
        "status": status,
        "title": title,
        "reason": reason,
        "record_id": record_id,
        "suggested_queries": _dedupe_text(queries),
    }


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for gap in gaps:
        key = str(gap.get("id") or "")
        if key in seen:
            continue
        seen.add(key)
        output.append(gap)
    output.sort(key=lambda gap: (_priority_rank(str(gap.get("priority") or "P2")), str(gap.get("type") or ""), str(gap.get("id") or "")))
    return output


def _skipped_queries(gaps: list[dict[str, Any]], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_queries = {_norm(item.get("query", "")) for item in selected}
    skipped: list[dict[str, Any]] = []
    for gap in gaps:
        if gap.get("status") != ACTIONABLE_STATUS:
            continue
        for query in gap.get("suggested_queries") or []:
            if _norm(query) not in selected_queries:
                skipped.append({"query": query, "gap_id": gap.get("id", ""), "reason": "max_queries_or_duplicate"})
    return skipped


def _evidence_by_claim(evidence: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in evidence:
        grouped.setdefault(str(row.get("claim_id") or ""), []).append(row)
    return grouped


def _quality_by_claim(ai_quality: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in ai_quality.get("claim_quality") or []:
        claim_id = str(row.get("claim_id") or "")
        claim_text = str(row.get("claim") or "")
        if claim_id:
            output[claim_id] = row
        if claim_text:
            output[claim_text] = row
    return output


def _suggestions_by_claim(deepen_suggestions: dict[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for item in deepen_suggestions.get("deepen_suggestions") or []:
        queries = [str(query) for query in item.get("next_search_queries") or [] if str(query).strip()]
        if item.get("claim_id"):
            output[str(item.get("claim_id"))] = queries
        if item.get("claim"):
            output[str(item.get("claim"))] = queries
    return output


def _claim_verdict(claim: dict[str, Any], quality: dict[str, Any]) -> str:
    if quality.get("verdict"):
        return str(quality.get("verdict"))
    notes = str(claim.get("notes") or "").lower()
    for verdict in ("not_found", "partial", "contradicted", "supported"):
        if f"verdict: {verdict}" in notes:
            return verdict
    return str(claim.get("status") or "open")


def _looks_needing_official(text: str) -> bool:
    lowered = text.lower()
    tokens = ("产品", "资质", "合规", "policy", "regulation", "api", "工具", "service", "端口", "官方", "current", "latest")
    return any(token in lowered for token in tokens)


def _looks_freshness_sensitive(text: str) -> bool:
    lowered = text.lower()
    tokens = ("仍", "当前", "最新", "可售", "有效", "价格", "政策", "资质", "端口", "监听", "running", "current", "latest", "available")
    return any(token in lowered for token in tokens)


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = _norm(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(str(value))
    return output


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 3)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())
