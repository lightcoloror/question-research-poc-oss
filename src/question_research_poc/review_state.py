from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .orchestrator import list_records
from .workflow_engine import GATE_AUDIT_FILENAME, NEXT_STEPS_FILENAME, ROUTE_FILENAME
from .workflow_engine import GATE_NEXT_STEP_RULES


def build_workflow_payload(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    route = _read_project_json(root / ROUTE_FILENAME)
    gate_audit = _read_project_json(root / GATE_AUDIT_FILENAME)
    next_steps = _read_project_json(root / NEXT_STEPS_FILENAME)
    artifacts = build_workflow_artifacts(root)
    return {
        "route": route,
        "gate_audit": gate_audit,
        "next_steps": next_steps,
        "artifacts": artifacts,
        "gate_details": build_gate_details(root, gate_audit=gate_audit, artifacts=artifacts),
        "has_route": bool(route),
        "has_gate_audit": bool(gate_audit),
        "has_next_steps": bool(next_steps),
        "review_queue_count": len(build_review_queue(root)),
    }


def build_workflow_artifacts(project_root: str | Path) -> list[dict[str, Any]]:
    root = Path(project_root)
    artifacts = [
        ("task_route", "任务路由", "task-route.json", "notes/task-route.md"),
        ("research_plan", "研究计划", "research-plan.json", "notes/research-plan.md"),
        ("gate_audit", "Gate 审计", "gate-audit.json", "notes/workflow-gate-audit.md"),
        ("next_steps", "下一步任务包", "workflow-next-steps.json", "notes/workflow-next-steps.md"),
        ("workflow_contract", "流程契约", "workflow-contract.json", "notes/workflow-contract.md"),
        ("multi_perspective_review", "多视角审查", "multi-perspective-review.json", "notes/multi-perspective-review.md"),
        ("reader_persona_review", "读者盲测", "reader-persona-review.json", "notes/reader-persona-review.md"),
        ("fallback_boundary", "Fallback / 工具边界", "", "notes/fallback-and-tool-boundary.md"),
    ]
    rows: list[dict[str, Any]] = []
    for artifact_id, title, json_rel, markdown_rel in artifacts:
        json_path = root / json_rel if json_rel else None
        markdown_path = root / markdown_rel if markdown_rel else None
        rows.append(
            {
                "id": artifact_id,
                "title": title,
                "json_path": str(json_path) if json_path else "",
                "markdown_path": str(markdown_path) if markdown_path else "",
                "json_exists": bool(json_path and json_path.exists()),
                "markdown_exists": bool(markdown_path and markdown_path.exists()),
                "complete": bool((not json_path or json_path.exists()) and markdown_path and markdown_path.exists()),
            }
        )
    return rows


def build_gate_details(
    project_root: str | Path,
    *,
    gate_audit: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    if not (root / "research.json").exists():
        return {}
    sources = list_records(root, "sources")
    claims = list_records(root, "claims")
    evidence = list_records(root, "evidence")
    reviews = list_records(root, "reviews")
    actual_artifacts = artifacts if artifacts is not None else build_workflow_artifacts(root)
    actual_gate_audit = gate_audit if gate_audit is not None else _read_project_json(root / GATE_AUDIT_FILENAME)
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(str(item.get("claim_id", "")), []).append(item)
    sources_by_id = {str(source.get("id", "")): source for source in sources}
    missing_artifacts = [item for item in actual_artifacts if not item.get("complete")]
    gates = actual_gate_audit.get("gates", []) if isinstance(actual_gate_audit, dict) else []
    details: dict[str, Any] = {}
    gate_rows = [gate for gate in gates if isinstance(gate, dict)]
    for gate in gate_rows:
        gate_id = str(gate.get("id", ""))
        rule = GATE_NEXT_STEP_RULES.get(gate_id, {})
        records: list[dict[str, Any]] = []
        if gate_id == "sources_present" and not sources:
            records.append(_detail_record("source", "", "还没有来源入库。", "添加来源或导入外部工具结果。", ui_focus="sourceInboxPanel"))
        elif gate_id == "source_quality_reviewed":
            records.extend(
                _detail_record("source", str(source.get("id", "")), str(source.get("title", "")), "标注来源质量。", ui_focus="reviewQueuePanel")
                for source in sources
                if str(source.get("quality", "unknown")) == "unknown"
            )
        elif gate_id == "claims_present" and not claims:
            records.append(_detail_record("claim", "", "还没有待验证主张。", "生成研究计划或手动添加主张。", ui_focus="claimsPanel"))
        elif gate_id == "evidence_present":
            if not evidence:
                records.append(_detail_record("evidence", "", "还没有证据卡。", "抓取正文、导入材料或手动添加证据。", ui_focus="evidencePanel"))
            records.extend(
                _detail_record("claim", str(claim.get("id", "")), str(claim.get("text", "")), "这个主张还没有任何证据卡。", ui_focus="reviewQueuePanel")
                for claim in claims
                if not evidence_by_claim.get(str(claim.get("id", "")))
            )
        elif gate_id == "verified_evidence_present":
            records.extend(
                _detail_record("evidence", str(item.get("id", "")), str(item.get("quote_or_note", "")), "审核候选证据，通过后才计入 verified。", ui_focus="reviewQueuePanel")
                for item in evidence
                if str(item.get("status", "candidate")) == "candidate"
            )
            records.extend(
                _detail_record("evidence", str(item.get("id", "")), str(item.get("quote_or_note", "")), "证据来自 poor 来源，只能作为线索或需人工确认。", ui_focus="reviewQueuePanel")
                for item in evidence
                if str(sources_by_id.get(str(item.get("source_id", "")), {}).get("quality", "")) == "poor"
            )
        elif gate_id == "counter_evidence_checked":
            records.extend(
                _detail_record("claim", str(claim.get("id", "")), str(claim.get("text", "")), "补充 contradicts/context 证据或反证搜索记录。", ui_focus="reviewQueuePanel")
                for claim in claims
                if not any(str(item.get("relation", "")) in {"contradicts", "context"} for item in evidence_by_claim.get(str(claim.get("id", "")), []))
            )
        elif gate_id == "result_file_chain_complete":
            records.extend(
                _detail_record("artifact", str(item.get("id", "")), str(item.get("title", "")), f"补齐 {item.get('markdown_path') or item.get('json_path')}", ui_focus="gatePanel")
                for item in missing_artifacts
            )
        elif gate_id == "human_reviews_recorded" and not reviews:
            records.append(_detail_record("review", "", "还没有人工/代理审核记录。", "至少完成一次来源或证据审核。", ui_focus="reviewQueuePanel"))
        details[gate_id] = {
            "gate_id": gate_id,
            "ok": bool(gate.get("ok")),
            "status": str(gate.get("status", "")),
            "severity": str(gate.get("severity", "")),
            "title": str(gate.get("title") or gate.get("description") or gate_id),
            "description": str(gate.get("description", "")),
            "current": gate.get("current", ""),
            "target": gate.get("target", ""),
            "why": _gate_why(gate, len(records)),
            "next_human_action": str(rule.get("human_action") or gate.get("next_gate") or ""),
            "next_agent_action": str(rule.get("agent_action") or gate.get("next_gate") or ""),
            "can_agent_execute": bool(rule.get("can_agent_execute", False)),
            "requires_human_confirmation": bool(rule.get("requires_human_confirmation", True)),
            "entrypoints": {
                "cli": rule.get("cli", []),
                "mcp": rule.get("mcp", []),
                "ui": rule.get("ui", []),
            },
            "ui_focus": _gate_ui_focus(gate_id),
            "record_count": len(records),
            "records": records,
        }
    return details


def build_review_queue(project_root: str | Path) -> list[dict[str, Any]]:
    root = Path(project_root)
    if not (root / "research.json").exists():
        return []
    return build_review_queue_from_records(
        list_records(root, "sources"),
        list_records(root, "claims"),
        list_records(root, "evidence"),
    )


def build_review_queue_from_records(
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources_by_id = {str(source.get("id", "")): source for source in sources}
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(str(item.get("claim_id", "")), []).append(item)
    queue: list[dict[str, Any]] = []
    for source in sources:
        if str(source.get("quality", "unknown")) == "unknown":
            queue.append(_queue_item("source_quality", str(source.get("id", "")), "来源未标质量", str(source.get("title", "")), "标为 good / mixed / poor。", priority="high", source_id=str(source.get("id", ""))))
    for item in evidence:
        source = sources_by_id.get(str(item.get("source_id", "")), {})
        if str(item.get("status", "candidate")) == "candidate":
            queue.append(_queue_item("candidate_evidence", str(item.get("id", "")), "候选证据待审核", str(item.get("quote_or_note", "")), "通过或拒绝这条证据。", priority="high", evidence_id=str(item.get("id", "")), claim_id=str(item.get("claim_id", "")), source_id=str(item.get("source_id", ""))))
        if str(source.get("quality", "")) == "poor":
            queue.append(_queue_item("poor_source_evidence", str(item.get("id", "")), "低质量来源证据", str(item.get("quote_or_note", "")), "确认是否只能作为线索，或拒绝该证据。", priority="high", evidence_id=str(item.get("id", "")), claim_id=str(item.get("claim_id", "")), source_id=str(item.get("source_id", ""))))
    for claim in claims:
        claim_id = str(claim.get("id", ""))
        claim_evidence = evidence_by_claim.get(claim_id, [])
        if not claim_evidence:
            queue.append(_queue_item("claim_without_evidence", claim_id, "主张没有证据", str(claim.get("text", "")), "补充来源或证据卡。", priority="medium", claim_id=claim_id))
        if not any(str(item.get("relation", "")) in {"contradicts", "context"} for item in claim_evidence):
            queue.append(
                _queue_item(
                    "missing_counter_evidence",
                    claim_id,
                    "建议补充反证检查",
                    str(claim.get("text", "")),
                    "补充反证搜索或 contradicts/context 证据；这不是最终答案硬阻塞。",
                    priority="low",
                    status="recommended_review",
                    requires_human_confirmation=False,
                    claim_id=claim_id,
                )
            )
    return queue


def _detail_record(record_type: str, record_id: str, title: str, action: str, *, ui_focus: str = "") -> dict[str, str]:
    return {
        "record_type": record_type,
        "record_id": record_id,
        "record_ref": f"{record_type}:{record_id}" if record_id else record_type,
        "title": title,
        "action": action,
        "ui_focus": ui_focus,
    }


def _queue_item(
    item_type: str,
    item_id: str,
    title: str,
    summary: str,
    action: str,
    *,
    priority: str = "medium",
    status: str = "needs_human_review",
    requires_human_confirmation: bool = True,
    **refs: str,
) -> dict[str, Any]:
    return {
        "item_type": item_type,
        "id": item_id,
        "record_ref": f"{item_type}:{item_id}",
        "title": title,
        "summary": summary,
        "action": action,
        "priority": priority,
        "status": status,
        "requires_human_confirmation": requires_human_confirmation,
        "suggested_ui_focus": _queue_ui_focus(item_type),
        "allowed_actions": _queue_allowed_actions(item_type),
        "refs": {key: value for key, value in refs.items() if value},
        **refs,
    }


def _gate_why(gate: dict[str, Any], record_count: int) -> str:
    if gate.get("ok"):
        if record_count:
            return f"Gate 已通过，但仍有 {record_count} 条相关记录值得检查。"
        return "Gate 已通过，没有待处理记录。"
    current = gate.get("current", "")
    target = gate.get("target", "")
    if record_count:
        return f"当前为 {current}，目标是 {target}；下面列出 {record_count} 条具体待处理对象。"
    return f"当前为 {current}，目标是 {target}；需要按下一步动作补齐。"


def _gate_ui_focus(gate_id: str) -> str:
    mapping = {
        "sources_present": "sourceInboxPanel",
        "source_quality_reviewed": "reviewQueuePanel",
        "claims_present": "claimsPanel",
        "evidence_present": "reviewQueuePanel",
        "verified_evidence_present": "reviewQueuePanel",
        "counter_evidence_checked": "reviewQueuePanel",
        "result_file_chain_complete": "gatePanel",
        "human_reviews_recorded": "reviewQueuePanel",
    }
    return mapping.get(gate_id, "gatePanel")


def _queue_ui_focus(item_type: str) -> str:
    if item_type == "source_quality":
        return "sourcesPanel"
    if item_type in {"candidate_evidence", "poor_source_evidence"}:
        return "evidencePanel"
    if item_type == "claim_without_evidence":
        return "evidencePanel"
    return "gatePanel"


def _queue_allowed_actions(item_type: str) -> list[str]:
    if item_type == "source_quality":
        return ["review_source_quality", "open_source"]
    if item_type in {"candidate_evidence", "poor_source_evidence"}:
        return ["review_evidence", "open_evidence"]
    if item_type == "claim_without_evidence":
        return ["add_evidence", "fetch_source_content", "open_claim"]
    if item_type == "missing_counter_evidence":
        return ["add_context_or_contradicting_evidence", "plan_counter_evidence_search", "open_claim"]
    return ["open_gate"]


def _read_project_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
