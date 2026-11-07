from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .dashboard import build_project_dashboard
from .local_tool_health import build_local_tool_health_dashboard
from .completeness_audit import audit_research_completeness
from .orchestrator import list_records
from .review_state import build_review_queue, build_workflow_payload
from .storage import load_project


PACK_SCHEMA = "question_research_pack.v1"
OBSIDIAN_EXPORT_SCHEMA = "question_research_obsidian_export.v1"
LOGSEQ_HANDOFF_SCHEMA = "question_research_logseq_handoff.v1"


def export_research_pack(root: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root)
    project = load_project(project_root)
    output = Path(output_dir) if output_dir else project_root / "exports" / "research-pack"
    output.mkdir(parents=True, exist_ok=True)

    sources = list_records(project_root, "sources")
    claims = list_records(project_root, "claims")
    evidence = list_records(project_root, "evidence")
    reviews = list_records(project_root, "reviews")
    workflow = build_workflow_payload(project_root)
    review_queue = build_review_queue(project_root)
    dashboard = build_project_dashboard(project_root, workflow=workflow, review_queue=review_queue)
    completeness = audit_research_completeness(project_root)
    local_tools = build_local_tool_health_dashboard()
    workflow_pack_complete = _workflow_pack_complete(workflow)
    pack_next_actions = list(dashboard.get("next_actions", []))
    if completeness.get("ready_for_answer") and not workflow_pack_complete:
        pack_next_actions = [
            "Answer readiness 已通过；当前缺口只表示 workflow artifact chain 不完整，不阻止基于已审核证据生成答案。",
            *pack_next_actions,
        ]

    files = {
        "research_brief": output / "research-brief.md",
        "source_quality_table": output / "source-quality-table.md",
        "evidence_table": output / "evidence-table.md",
        "open_questions": output / "open-questions.md",
        "next_actions": output / "next-actions.md",
    }
    files["research_brief"].write_text(
        _render_research_brief(project, project_root, dashboard, workflow, review_queue, local_tools),
        encoding="utf-8",
    )
    files["source_quality_table"].write_text(_render_source_quality_table(project.question, sources), encoding="utf-8")
    files["evidence_table"].write_text(_render_evidence_table(project.question, claims, sources, evidence), encoding="utf-8")
    files["open_questions"].write_text(_render_open_questions(project.question, dashboard, review_queue), encoding="utf-8")
    files["next_actions"].write_text(_render_next_actions(project_root, project.question, dashboard, workflow, review_queue), encoding="utf-8")

    return {
        "ok": True,
        "schema": PACK_SCHEMA,
        "root": str(project_root),
        "output_dir": str(output),
        "files": {key: str(path) for key, path in files.items()},
        "human_review_required": True,
        "answer_ready": bool(completeness.get("ready_for_answer")),
        "workflow_pack_complete": workflow_pack_complete,
        "answer_readiness": completeness,
        "review_queue_count": len(review_queue),
        "next_actions": pack_next_actions,
        "counts": {
            "sources": len(sources),
            "claims": len(claims),
            "evidence": len(evidence),
            "reviews": len(reviews),
        },
    }


def export_research_pack_to_obsidian(root: str | Path, vault: str | Path, folder: str = "AI Research/问题导向研究审核包") -> dict[str, Any]:
    project_root = Path(root)
    vault_root = Path(vault)
    target_dir = vault_root / Path(folder)
    pack = export_research_pack(project_root)
    target_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str] = {}
    for key, source_path in pack.get("files", {}).items():
        source = Path(str(source_path))
        target = target_dir / source.name
        shutil.copyfile(source, target)
        copied[key] = str(target)

    index_path = target_dir / "README.md"
    index_path.write_text(_render_obsidian_export_index(project_root, pack, copied), encoding="utf-8")
    copied["index"] = str(index_path)
    return {
        "ok": True,
        "schema": OBSIDIAN_EXPORT_SCHEMA,
        "root": str(project_root),
        "vault": str(vault_root),
        "folder": folder,
        "output_dir": str(target_dir),
        "files": copied,
        "human_review_required": True,
        "direct_write": False,
        "boundary": "Only writes Markdown review files into the selected Obsidian folder; it does not publish final conclusions or write to Logseq.",
    }


def create_logseq_review_handoff(root: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root)
    project = load_project(project_root)
    pack = export_research_pack(project_root)
    output = Path(output_dir) if output_dir else project_root / "exports" / "logseq-handoff"
    output.mkdir(parents=True, exist_ok=True)
    handoff_path = output / "logseq-review-handoff.md"
    handoff_path.write_text(_render_logseq_handoff(project.question, project_root, pack), encoding="utf-8")
    return {
        "ok": True,
        "schema": LOGSEQ_HANDOFF_SCHEMA,
        "root": str(project_root),
        "output_dir": str(output),
        "path": str(handoff_path),
        "proposed_page_title": f"研究审核/{project.question}",
        "human_review_required": True,
        "direct_write": False,
        "boundary": "Creates a review handoff file only; it does not call the Logseq API or write blocks.",
    }


def _render_research_brief(
    project: Any,
    project_root: Path,
    dashboard: dict[str, Any],
    workflow: dict[str, Any],
    review_queue: list[dict[str, Any]],
    local_tools: dict[str, Any],
) -> str:
    metrics = dashboard.get("metrics", {})
    stage_detail = dashboard.get("stage_detail", {}) if isinstance(dashboard.get("stage_detail"), dict) else {}
    gate_audit = workflow.get("gate_audit") if isinstance(workflow, dict) else {}
    gates = gate_audit.get("gates", []) if isinstance(gate_audit, dict) else []
    lines = [
        f"# 研究简报：{project.question}",
        "",
        "Human review required: this pack is a review artifact, not a final publication.",
        "",
        "## 基本状态",
        "",
        f"- 项目路径：`{project_root}`",
        f"- 当前阶段：`{dashboard.get('stage', 'unknown')}` {stage_detail.get('stage_label', '')}",
        f"- 阻塞 Gate：`{stage_detail.get('blocking_gate', '')}`",
        f"- 人工下一步：{stage_detail.get('next_human_action', '')}",
        f"- Agent 下一步：{stage_detail.get('next_agent_action', '')}",
        f"- 来源数量：{metrics.get('sources', 0)}",
        f"- 主张数量：{metrics.get('claims', 0)}",
        f"- 证据数量：{metrics.get('evidence', 0)}",
        f"- 已验证证据：{metrics.get('verified_evidence', 0)}",
        f"- 审核队列：{len(review_queue)}",
        f"- 主张覆盖率：{metrics.get('claim_coverage_percent', 0)}%",
        f"- 已验证覆盖率：{metrics.get('verified_claim_coverage_percent', 0)}%",
        "",
        "## 阶段判断原因",
        "",
    ]
    lines.extend(f"- {reason}" for reason in stage_detail.get("reasons", [])) if stage_detail.get("reasons") else lines.append("- 暂无阶段原因。")
    lines.extend(
        [
            "",
        "## Gate 状态",
        "",
        "| Gate | 状态 | 当前 / 目标 | 说明 |",
        "| --- | --- | --- | --- |",
        ]
    )
    if gates:
        for gate in gates:
            status = "pass" if gate.get("ok") else str(gate.get("severity") or "fail")
            lines.append(
                "| {title} | `{status}` | {current} / {target} | {description} |".format(
                    title=_md(gate.get("title") or gate.get("id") or ""),
                    status=_md(status),
                    current=_md(gate.get("current", "")),
                    target=_md(gate.get("target", "")),
                    description=_md(gate.get("description", "")),
                )
            )
    else:
        lines.append("| Gate audit | `missing` | 0 / 1 | 尚未运行 Gate 审计。 |")
    lines.extend(["", "## 审核队列概览", ""])
    if review_queue:
        for item in review_queue[:12]:
            lines.append(f"- `{item.get('item_type')}` {item.get('title')}: {item.get('summary')} -> {item.get('action')}")
        if len(review_queue) > 12:
            lines.append(f"- 另有 {len(review_queue) - 12} 项未列出，请看 `open-questions.md`。")
    else:
        lines.append("- 当前没有待人工审核项。")
    lines.extend(["", "## 本地工具状态", ""])
    for tool in local_tools.get("tools", []):
        available = "available" if tool.get("available") else "missing"
        lines.append(f"- `{tool.get('name')}`: {available}; {tool.get('recommended_next_action', '')}")
    lines.extend(["", "## 重要产物入口", ""])
    for artifact in workflow.get("artifacts", []):
        status = "complete" if artifact.get("complete") else "missing"
        lines.append(f"- `{status}` {artifact.get('title')}: {artifact.get('markdown_path') or artifact.get('json_path')}")
    return "\n".join(lines).rstrip() + "\n"


def _render_source_quality_table(question: str, sources: list[dict[str, Any]]) -> str:
    lines = [
        f"# 来源质量表：{question}",
        "",
        "Human review required: `unknown` and `poor` sources must be reviewed before final use.",
        "",
        "| Source ID | Quality | Type | Title | Location | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if sources:
        for source in sources:
            lines.append(
                "| {id} | `{quality}` | {type} | {title} | {location} | {notes} |".format(
                    id=_md(source.get("id", "")),
                    quality=_md(source.get("quality", "unknown")),
                    type=_md(source.get("source_type", "")),
                    title=_md(source.get("title", "")),
                    location=_md(source.get("url") or source.get("path") or ""),
                    notes=_md(source.get("notes") or source.get("quality_reason") or ""),
                )
            )
    else:
        lines.append("|  | `missing` |  | 尚无来源 |  |  |")
    return "\n".join(lines).rstrip() + "\n"


def _render_evidence_table(question: str, claims: list[dict[str, Any]], sources: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
    claims_by_id = {str(claim.get("id", "")): claim for claim in claims}
    sources_by_id = {str(source.get("id", "")): source for source in sources}
    lines = [
        f"# 证据表：{question}",
        "",
        "Human review required: candidate evidence is not final evidence.",
        "",
        "| Evidence ID | Status | Relation | Confidence | Claim | Source | Quote / Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if evidence:
        for item in evidence:
            claim = claims_by_id.get(str(item.get("claim_id", "")), {})
            source = sources_by_id.get(str(item.get("source_id", "")), {})
            lines.append(
                "| {id} | `{status}` | `{relation}` | `{confidence}` | {claim} | {source} | {quote} |".format(
                    id=_md(item.get("id", "")),
                    status=_md(item.get("status", "candidate")),
                    relation=_md(item.get("relation", "unknown")),
                    confidence=_md(item.get("confidence", "unknown")),
                    claim=_md(claim.get("text") or item.get("claim_id") or ""),
                    source=_md(source.get("title") or item.get("source_id") or ""),
                    quote=_md(_preview(item.get("quote_or_note", ""), 180)),
                )
            )
    else:
        lines.append("|  | `missing` |  |  | 尚无证据 |  |  |")
    return "\n".join(lines).rstrip() + "\n"


def _render_open_questions(question: str, dashboard: dict[str, Any], review_queue: list[dict[str, Any]]) -> str:
    lines = [
        f"# 开放问题：{question}",
        "",
        "Human review required: these are blockers or uncertainty points.",
        "",
        "## 缺口清单",
        "",
    ]
    gaps = dashboard.get("gaps", [])
    lines.extend(f"- {gap}" for gap in gaps) if gaps else lines.append("- 当前 dashboard 没有明显缺口。")
    lines.extend(["", "## 待审核对象", ""])
    if review_queue:
        for item in review_queue:
            refs = ", ".join(f"{key}={value}" for key, value in item.items() if key.endswith("_id") and value)
            lines.append(f"- `{item.get('item_type')}` {item.get('title')}: {item.get('summary')} -> {item.get('action')} {refs}")
    else:
        lines.append("- 当前没有待审核对象。")
    return "\n".join(lines).rstrip() + "\n"


def _render_next_actions(project_root: Path, question: str, dashboard: dict[str, Any], workflow: dict[str, Any], review_queue: list[dict[str, Any]]) -> str:
    audit = workflow.get("gate_audit") if isinstance(workflow, dict) else {}
    next_steps = audit.get("next_steps", []) if isinstance(audit, dict) else []
    lines = [
        f"# 下一步行动：{question}",
        "",
        "Human review required: automated agents may run only safe steps; source/evidence decisions need human approval.",
        "",
        "## Dashboard 建议",
        "",
    ]
    actions = dashboard.get("next_actions", [])
    lines.extend(f"{idx}. {action}" for idx, action in enumerate(actions, start=1)) if actions else lines.append("- 当前没有下一步建议。")
    lines.extend(["", "## Gate 下一步", ""])
    if next_steps:
        for step in next_steps:
            lines.append(f"{step.get('order', '')}. `{step.get('gate_id')}`")
            lines.append(f"   - Human: {step.get('human_action')}")
            lines.append(f"   - Agent: {step.get('agent_action')}")
    else:
        lines.append("- 尚无 Gate next steps。")
    lines.extend(["", "## 可复制命令", ""])
    lines.append(f"- 查看状态：`.\\scripts\\research-poc.ps1 get-project-status --project \"{project_root}\"`")
    lines.append(f"- 查看审核队列：`.\\scripts\\research-poc.ps1 get-review-queue --project \"{project_root}\"`")
    lines.append(f"- 导出研究包：`.\\scripts\\research-poc.ps1 export-research-pack --project \"{project_root}\"`")
    if review_queue:
        lines.append("- 审核队列存在时，不要让 Agent 自动通过来源或证据。")
    return "\n".join(lines).rstrip() + "\n"


def _render_obsidian_export_index(project_root: Path, pack: dict[str, Any], copied: dict[str, str]) -> str:
    lines = [
        "# 问题导向研究审核包",
        "",
        "Human review required: this folder is a review package, not an automatic publication.",
        "",
        f"- Project: `{project_root}`",
        f"- Source pack: `{pack.get('output_dir', '')}`",
        f"- Review queue: {pack.get('review_queue_count', 0)}",
        f"- Direct write: `false`",
        "",
        "## Files",
        "",
    ]
    for key, path in copied.items():
        lines.append(f"- `{key}`: [[{Path(path).name}]]")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 这些文件只是进入 Obsidian 的人工审核材料。",
            "- 不会自动改变来源质量、证据状态或最终结论。",
            "- 不会调用 Logseq API。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_logseq_handoff(question: str, project_root: Path, pack: dict[str, Any]) -> str:
    lines = [
        f"# Logseq 审核包：{question}",
        "",
        "不直接写入 Logseq；本文件只提供人工审核和后续写回准备。",
        "",
        "## Proposed Page",
        "",
        f"- Title: `研究审核/{question}`",
        f"- Project: `{project_root}`",
        f"- Research pack: `{pack.get('output_dir', '')}`",
        f"- Direct write: `false`",
        f"- Human review required: `true`",
        "",
        "## Source Files",
        "",
    ]
    for key, path in pack.get("files", {}).items():
        lines.append(f"- `{key}`: `{path}`")
    lines.extend(
        [
            "",
            "## Human Approval Checklist",
            "",
            "- [ ] 来源质量已经人工确认。",
            "- [ ] candidate evidence 已经逐条通过、拒绝或退回修改。",
            "- [ ] 反证/限制条件已经检查。",
            "- [ ] 最终结论强度和不确定性已经人工确认。",
            "- [ ] 写回目标页面标题和结构已经确认。",
            "",
            "## Safe Logseq Status Check",
            "",
            "```powershell",
            "$env:QRP_WORKSPACE_ROOT\\scripts\\logseq-api.ps1 status",
            "```",
            "",
            "## Writeback Boundary",
            "",
            "- 本工具不读取、不输出、不写入本地 Logseq API 密钥。",
            "- 本工具不调用 Logseq 写 API。",
            "- 真实写回必须由人工确认具体页面、块内容和写入命令后单独执行。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _preview(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _md(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _workflow_pack_complete(workflow: dict[str, Any]) -> bool:
    artifacts = workflow.get("artifacts") if isinstance(workflow, dict) else None
    if not isinstance(artifacts, list):
        return False
    return all(bool(artifact.get("complete")) for artifact in artifacts if isinstance(artifact, dict))
