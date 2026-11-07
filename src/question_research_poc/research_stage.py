from __future__ import annotations

from pathlib import Path
from typing import Any

from .orchestrator import list_records
from .research_plan import PLAN_FILENAME


STAGE_ORDER = [
    "not_initialized",
    "question_defined",
    "research_plan_ready",
    "sources_collected",
    "source_quality_reviewed",
    "claims_extracted",
    "evidence_reviewed",
    "answer_draft_ready",
    "export_ready",
]


STAGE_LABELS = {
    "not_initialized": "项目尚未初始化",
    "question_defined": "问题已定义",
    "research_plan_ready": "研究计划已生成",
    "sources_collected": "来源已收集",
    "source_quality_reviewed": "来源质量已审核",
    "claims_extracted": "主张已提取",
    "evidence_reviewed": "证据已审核",
    "answer_draft_ready": "阶段性回答可生成",
    "export_ready": "研究包已导出",
}


def classify_research_stage(root: str | Path, *, workflow: dict[str, Any] | None = None, review_queue: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    project_root = Path(root)
    if not (project_root / "research.json").exists():
        return _stage(
            "not_initialized",
            blocking_gate="project_initialized",
            next_human_action="创建研究项目并填写研究问题。",
            next_agent_action="运行 init_project 或 CLI init。",
            reasons=["项目目录里没有 research.json。"],
        )

    sources = list_records(project_root, "sources")
    claims = list_records(project_root, "claims")
    evidence = list_records(project_root, "evidence")
    queue = review_queue if review_queue is not None else []
    flow = workflow if workflow is not None else {}
    gate_audit = flow.get("gate_audit") if isinstance(flow, dict) else {}
    plan_exists = (project_root / PLAN_FILENAME).exists()
    export_exists = _research_pack_exists(project_root)
    draft_exists = (project_root / "notes" / "answer-draft.md").exists()
    all_sources_reviewed = bool(sources) and all(str(source.get("quality", "unknown")) in {"good", "mixed", "poor"} for source in sources)
    verified = [item for item in evidence if item.get("status") == "verified"]
    candidate = [item for item in evidence if str(item.get("status", "candidate")) == "candidate"]
    has_counter = any(str(item.get("relation", "")) in {"contradicts", "context"} for item in evidence)
    can_proceed = bool(gate_audit.get("can_proceed", gate_audit.get("ok", False))) if isinstance(gate_audit, dict) else False

    if export_exists and (can_proceed or bool(verified)):
        return _stage(
            "export_ready",
            blocking_gate="human_final_review",
            next_human_action="人工阅读研究包，决定是否导出到 Obsidian 或生成 Logseq 审核包。",
            next_agent_action="只能读取研究包和列出待审核项，不得自动写回知识库。",
            reasons=["exports/research-pack 下的五个 Markdown 文件已存在。"],
        )
    if draft_exists or can_proceed:
        return _stage(
            "answer_draft_ready",
            blocking_gate="final_human_review",
            next_human_action="人工审阅阶段性回答、反证和缺口后再决定是否导出。",
            next_agent_action="运行 export_research_pack，生成可读审核包。",
            reasons=["Gate 审计允许进入下一阶段，或 answer-draft.md 已存在。"],
        )
    if verified and not candidate:
        return _stage(
            "evidence_reviewed",
            blocking_gate="counter_evidence_checked" if not has_counter else "answer_draft_ready",
            next_human_action="检查反证/context 是否足够，再生成阶段性回答。",
            next_agent_action="运行 audit-gates 或 draft-answer；缺反证时先补 counter-evidence search。",
            reasons=[f"已有 {len(verified)} 条 verified evidence，且没有 candidate evidence 待审。"],
        )
    if claims:
        reason = "已有主张，正在等待证据补充或证据审核。"
        if evidence:
            reason = f"已有 {len(evidence)} 条证据，其中 {len(candidate)} 条 candidate、{len(verified)} 条 verified。"
        return _stage(
            "claims_extracted",
            blocking_gate="verified_evidence_present" if evidence else "evidence_present",
            next_human_action="审核候选证据，或为无证据主张补充证据。",
            next_agent_action="调用 web-content-fetcher / ai-research-workflow / video-knowledge-pipeline 生成候选证据；不得自动通过证据。",
            reasons=[reason],
            review_queue_count=len(queue),
        )
    if all_sources_reviewed:
        return _stage(
            "source_quality_reviewed",
            blocking_gate="claims_present",
            next_human_action="确认哪些判断需要被验证。",
            next_agent_action="运行 plan-research --add-claims 或 add_claim 生成可验证主张。",
            reasons=["所有来源都有 good/mixed/poor 质量标注。"],
        )
    if sources:
        unknown = [source for source in sources if str(source.get("quality", "unknown")) == "unknown"]
        return _stage(
            "sources_collected",
            blocking_gate="source_quality_reviewed",
            next_human_action="给所有来源标注质量，必要时说明低质量来源只能作线索。",
            next_agent_action="列出未标质量来源和建议理由，不得替代最终人工判断。",
            reasons=[f"已有 {len(sources)} 个来源，其中 {len(unknown)} 个仍是 unknown。"],
            review_queue_count=len(queue),
        )
    if plan_exists:
        return _stage(
            "research_plan_ready",
            blocking_gate="sources_present",
            next_human_action="确认搜索任务后导入来源。",
            next_agent_action="运行 research-search、fetch-source-content 或视频处理计划来收集来源。",
            reasons=["research-plan.json 已存在，但项目还没有来源。"],
        )
    return _stage(
        "question_defined",
        blocking_gate="research_plan_present",
        next_human_action="确认问题边界和输出目标。",
        next_agent_action="运行 plan-research --add-claims 生成研究计划。",
        reasons=["项目已创建，但还没有 research-plan.json。"],
    )


def _stage(
    stage_id: str,
    *,
    blocking_gate: str,
    next_human_action: str,
    next_agent_action: str,
    reasons: list[str],
    review_queue_count: int = 0,
) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "stage_label": STAGE_LABELS.get(stage_id, stage_id),
        "stage_index": STAGE_ORDER.index(stage_id) if stage_id in STAGE_ORDER else -1,
        "stage_order": STAGE_ORDER,
        "blocking_gate": blocking_gate,
        "next_human_action": next_human_action,
        "next_agent_action": next_agent_action,
        "reasons": reasons,
        "review_queue_count": review_queue_count,
    }


def _research_pack_exists(project_root: Path) -> bool:
    output = project_root / "exports" / "research-pack"
    required = [
        "research-brief.md",
        "source-quality-table.md",
        "evidence-table.md",
        "open-questions.md",
        "next-actions.md",
    ]
    return all((output / name).exists() for name in required)
