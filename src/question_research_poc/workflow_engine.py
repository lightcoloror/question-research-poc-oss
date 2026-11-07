from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import now_iso
from .orchestrator import draft_answer, list_records
from .research_plan import PLAN_FILENAME
from .storage import ensure_project_dirs, load_project, write_json


ROUTE_FILENAME = "task-route.json"
GATE_AUDIT_FILENAME = "gate-audit.json"
PERSPECTIVE_REVIEW_FILENAME = "multi-perspective-review.json"
PERSONA_REVIEW_FILENAME = "reader-persona-review.json"
NEXT_STEPS_FILENAME = "workflow-next-steps.json"
WORKFLOW_CONTRACT_FILENAME = "workflow-contract.json"

GATE_CONTRACT_SOURCE = {
    "type": "adapted_local_contract",
    "source": "domain-neutral readiness contract",
    "pattern": "readiness payload with ok/gates/next_gate/next_steps/operator_boundary",
    "note": "Only the domain-neutral workflow contract is reused; insurance/CRM-specific code is not imported.",
}

REFERENCE_WORKFLOW_SOURCES = [
    {
        "path": "local-reference://task-gate-workflow",
        "reused_patterns": [
            "task type to hard gate trigger matrix",
            "hard gate result file binding",
            "three-layer review chain",
            "persona blind review before publish/final delivery",
            "stop-and-report fallback on missing facts or conflicts",
        ],
    },
    {
        "path": "local-reference://route-first-image-workflow",
        "reused_patterns": [
            "route first, then choose mode",
            "checkpoint self-audit before execution",
            "explicit red-line checklist",
            "fallback tree instead of blind retry",
        ],
    },
    {
        "path": "local-reference://deterministic-extraction-strategies",
        "reused_patterns": [
            "script first, AI second for deterministic extraction",
            "contact sheet style human validation after batch output",
            "regenerate when prompt/tool failure is cheaper than patching around bad output",
        ],
    },
]

TASK_TRIGGER_MATRIX = [
    {
        "id": "new_research",
        "signals": ["新问题", "研究", "分析", "帮我找", "怎么做"],
        "route": "deep_research",
        "hard_gate_chain": ["task_route_present", "research_plan_present", "sources_present", "source_quality_reviewed", "evidence_present", "verified_evidence_present"],
        "result_files": ["task-route.md", "research-plan.md", "workflow-gate-audit.md"],
    },
    {
        "id": "source_material_ingest",
        "signals": ["url", "网页", "pdf", "文档", "资料", "本地文件"],
        "route": "source_ingest",
        "hard_gate_chain": ["task_route_present", "source_artifact_written", "source_quality_reviewed"],
        "result_files": ["task-route.md", "source artifact json/markdown"],
    },
    {
        "id": "video_knowledge_ingest",
        "signals": ["视频", "课程", "讲课", "讲解", "bilibili", "youtube", "mp4"],
        "route": "video_knowledge_ingest",
        "hard_gate_chain": ["task_route_present", "video_bundle_written", "source_quality_reviewed"],
        "result_files": ["task-route.md", "video review bundle", "structured video markdown"],
    },
    {
        "id": "answer_or_publish",
        "signals": ["能发了吗", "最终回答", "发布", "交付", "完整了吗"],
        "route": "final_answer_review",
        "hard_gate_chain": ["multi_perspective_review_present", "reader_persona_review_present", "result_file_chain_complete"],
        "result_files": ["multi-perspective-review.md", "reader-persona-review.md", "workflow-gate-audit.md"],
    },
]

DEFAULT_READER_PERSONAS = [
    {"id": "expert", "name": "领域专家", "distance": "near", "focus": "事实精度、术语边界、证据强度。"},
    {"id": "skeptic", "name": "强怀疑读者", "distance": "opposed", "focus": "反例、逻辑跳跃、过度概括。"},
    {"id": "practitioner", "name": "实践执行者", "distance": "applied", "focus": "下一步是否可执行、工具边界是否清楚。"},
    {"id": "review_learner", "name": "复习型读者", "distance": "far", "focus": "结构是否可检索、可复习、能否回到证据。"},
]

GATE_NEXT_STEP_RULES: dict[str, dict[str, Any]] = {
    "task_route_present": {
        "human_action": "确认当前任务应该走哪个材料处理路径。",
        "agent_action": "运行 route-research-task 生成 task-route.md/json。",
        "cli": ["python -m question_research_poc.cli route-research-task --project <project>"],
        "mcp": ["route_research_task"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "research_plan_present": {
        "human_action": "确认研究问题和输出目标没有偏题。",
        "agent_action": "运行 plan-research --add-claims 生成研究计划、子问题、搜索任务和初始主张。",
        "cli": ["python -m question_research_poc.cli plan-research --project <project> --add-claims"],
        "mcp": ["build_research_plan"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "sources_present": {
        "human_action": "提供或确认至少一个可信材料来源。",
        "agent_action": "优先调用 ai-research-workflow/web-content-fetcher/video-knowledge-pipeline 导入来源，不在总控层重做底层抓取。",
        "cli": ["python -m question_research_poc.cli add-source --project <project> --title <title> --url <url>"],
        "mcp": ["add_source", "import_ai_research_result", "fetch_source_content"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "source_quality_reviewed": {
        "human_action": "把每个来源标为 good/mixed/poor，并说明低质量来源是否只能作线索。",
        "agent_action": "列出未标注来源，给出建议质量理由；不能替代最终人工质量判断。",
        "cli": ["python -m question_research_poc.cli list-records --project <project> --kind sources"],
        "mcp": ["list_records"],
        "ui": ["/"],
        "can_agent_execute": False,
        "requires_human_confirmation": True,
    },
    "claims_present": {
        "human_action": "确认哪些判断需要被验证，而不是只写泛泛主题。",
        "agent_action": "从研究计划或材料候选中生成可验证主张。",
        "cli": ["python -m question_research_poc.cli add-claim --project <project> --text <claim>"],
        "mcp": ["add_claim", "build_research_plan"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "evidence_present": {
        "human_action": "确认证据摘录是否真的对应主张。",
        "agent_action": "抓取正文或导入外部工具结果，生成候选 evidence card。",
        "cli": ["python -m question_research_poc.cli fetch-source --project <project> --source-id <id> --create-candidate-evidence"],
        "mcp": ["fetch_source_content", "add_evidence"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "verified_evidence_present": {
        "human_action": "人工审核至少一条证据，把可信证据标为 verified。",
        "agent_action": "只整理证据和指出风险，不自动把候选证据升级为 verified。",
        "cli": ["python -m question_research_poc.cli review-evidence --project <project> --evidence-id <id> --status verified"],
        "mcp": ["review_evidence"],
        "ui": ["/"],
        "can_agent_execute": False,
        "requires_human_confirmation": True,
    },
    "counter_evidence_checked": {
        "human_action": "确认是否需要反证搜索、限制条件或不同观点来源。",
        "agent_action": "安排 counter-evidence search 或导入 contradicts/context 证据。",
        "cli": ["python -m question_research_poc.cli plan-research --project <project> --add-claims"],
        "mcp": ["build_research_plan", "add_evidence"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "multi_perspective_review_present": {
        "human_action": "查看事实、逻辑、反证、可复习性四类审查是否覆盖关键风险。",
        "agent_action": "运行 multi-perspective-review 生成审查文件和 fallback/tool-boundary 文档。",
        "cli": ["python -m question_research_poc.cli multi-perspective-review --project <project>"],
        "mcp": ["run_multi_perspective_review"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "reader_persona_review_present": {
        "human_action": "查看不同认知距离读者的盲测结果，确认是否存在定位不清或可读性断裂。",
        "agent_action": "运行 reader-persona-review，产出 reader-persona-review.md/json。",
        "cli": ["python -m question_research_poc.cli reader-persona-review --project <project>"],
        "mcp": ["run_reader_persona_review"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "result_file_chain_complete": {
        "human_action": "确认目标阶段要求的 result 文件链齐全后再交付。",
        "agent_action": "运行 audit-gates --target-stage final_answer 检查缺失文件；缺失则只输出 blocker 和 next_steps。",
        "cli": ["python -m question_research_poc.cli audit-gates --project <project> --target-stage final_answer"],
        "mcp": ["audit_research_gates"],
        "ui": ["/"],
        "can_agent_execute": True,
        "requires_human_confirmation": False,
    },
    "human_reviews_recorded": {
        "human_action": "记录至少一次来源或证据审核结论。",
        "agent_action": "展示待审核项和建议审核理由；不能绕过人工审核。",
        "cli": ["python -m question_research_poc.cli list-records --project <project> --kind reviews"],
        "mcp": ["list_records"],
        "ui": ["/"],
        "can_agent_execute": False,
        "requires_human_confirmation": True,
    },
}


def route_research_task(
    root: str | Path,
    *,
    question: str | None = None,
    material_hint: str = "",
    write: bool = True,
) -> dict[str, Any]:
    """Route a research task before running tools.

    The route is intentionally deterministic. It is a workflow contract, not a
    model judgment: agents can override it, but the default path is auditable.
    """
    paths = ensure_project_dirs(root)
    project = load_project(root)
    text = f"{question or project.question} {material_hint}".lower()
    sources = list_records(root, "sources")
    claims = list_records(root, "claims")
    evidence = list_records(root, "evidence")
    verified = [row for row in evidence if row.get("status") == "verified"]

    task_type = _task_type_from_text(text)

    if task_type == "video_knowledge_ingest" or _looks_like_video(text, sources):
        route = "video_knowledge_ingest"
        reason = "任务或来源包含视频/课程/讲解材料，应先交给 video-knowledge-pipeline 提取全量知识。"
        next_tools = ["video-knowledge-pipeline", "question-research-poc"]
    elif task_type == "source_material_ingest" or _looks_like_source_ingest(text, sources):
        route = "source_ingest"
        reason = "任务包含 URL/网页/PDF/本地资料，优先入库并抓取正文，不急着生成结论。"
        next_tools = ["web-content-fetcher", "bookwiki / ebook_markdown_pipeline", "question-research-poc"]
    elif task_type == "answer_or_publish":
        route = "final_answer_review"
        reason = "任务在询问能否交付/发布，应先检查多视角审查、读者盲测和 result 文件链。"
        next_tools = ["question-research-poc"]
    elif claims and verified:
        route = "quick_answer"
        reason = "已有主张和已审核证据，可以先生成阶段性回答。"
        next_tools = ["question-research-poc"]
    elif sources or claims:
        route = "deep_research"
        reason = "已有部分材料但证据链不足，需要继续搜索、抓取、审核和反证检查。"
        next_tools = ["ai-research-workflow", "web-content-fetcher", "question-research-poc"]
    else:
        route = "deep_research"
        reason = "项目刚启动，默认先建研究计划，再按框架搜索。"
        next_tools = ["question-research-poc", "ai-research-workflow"]

    result = {
        "schema": "research_task_route.v1",
        "root": str(paths["root"]),
        "question": question or project.question,
        "material_hint": material_hint,
        "task_type": task_type,
        "route": route,
        "reason": reason,
        "generated_at": now_iso(),
        "reference_workflow_sources": REFERENCE_WORKFLOW_SOURCES,
        "trigger_matrix_match": _trigger_matrix_for_route(route),
        "next_tools": next_tools,
        "hard_gates": _hard_gates_for_route(route),
        "required_result_files": _required_result_files_for_route(route),
        "fallback_plan": _fallback_plan_for_route(route),
        "tool_boundaries": tool_boundaries(),
    }
    if write:
        write_json(paths["root"] / ROUTE_FILENAME, result)
        write_json(paths["root"] / WORKFLOW_CONTRACT_FILENAME, workflow_contract())
        (paths["notes"] / "task-route.md").write_text(render_task_route_markdown(result), encoding="utf-8")
        (paths["notes"] / "workflow-contract.md").write_text(render_workflow_contract_markdown(workflow_contract()), encoding="utf-8")
    return result


def audit_research_gates(root: str | Path, *, target_stage: str = "answer_draft", write: bool = True) -> dict[str, Any]:
    paths = ensure_project_dirs(root)
    project = load_project(root)
    sources = list_records(root, "sources")
    claims = list_records(root, "claims")
    evidence = list_records(root, "evidence")
    reviews = list_records(root, "reviews")
    verified = [row for row in evidence if row.get("status") == "verified"]
    quality_marked = [row for row in sources if row.get("quality") in {"good", "mixed", "poor"}]
    contradictory = [row for row in evidence if row.get("relation") == "contradicts"]
    required_result_files = _required_result_files_for_stage(target_stage)
    missing_result_files = _missing_note_files(paths["notes"], required_result_files)
    final_stage = target_stage in {"final_answer", "publish", "delivery"}

    gates = [
        _gate("project_initialized", True, "项目已初始化。", current="存在", target="存在"),
        _gate("task_route_present", (paths["root"] / ROUTE_FILENAME).exists(), "已生成任务路由文件 task-route.md/json。", current="存在" if (paths["root"] / ROUTE_FILENAME).exists() else "缺失", target="task-route.md/json"),
        _gate("research_plan_present", (paths["root"] / PLAN_FILENAME).exists(), "已生成研究计划 research-plan.md/json。", current="存在" if (paths["root"] / PLAN_FILENAME).exists() else "缺失", target="research-plan.md/json"),
        _gate("sources_present", bool(sources), "已有来源入库。", current=len(sources), target=">=1"),
        _gate("source_quality_reviewed", bool(sources) and len(quality_marked) == len(sources), "所有来源都应有 good/mixed/poor 质量标注。", current=f"{len(quality_marked)}/{len(sources)}", target="全部来源"),
        _gate("claims_present", bool(claims), "已有待验证主张/子问题。", current=len(claims), target=">=1"),
        _gate("evidence_present", bool(evidence), "已有证据卡。", current=len(evidence), target=">=1"),
        _gate("verified_evidence_present", bool(verified), "至少有一条已审核证据。", current=len(verified), target=">=1"),
        _gate("counter_evidence_checked", bool(contradictory) or _has_counter_search(paths["root"] / PLAN_FILENAME), "已安排或记录反证检查。", severity="warn", current=len(contradictory), target="反证搜索或 contradicts/context evidence"),
        _gate("multi_perspective_review_present", (paths["root"] / PERSPECTIVE_REVIEW_FILENAME).exists(), "已生成多视角审查文件。", severity="warn", current="存在" if (paths["root"] / PERSPECTIVE_REVIEW_FILENAME).exists() else "缺失", target="multi-perspective-review.md/json"),
        _gate("reader_persona_review_present", (paths["root"] / PERSONA_REVIEW_FILENAME).exists(), "已生成 Reader Persona 盲测文件。", severity="block" if final_stage else "warn", current="存在" if (paths["root"] / PERSONA_REVIEW_FILENAME).exists() else "缺失", target="reader-persona-review.md/json"),
        _gate("result_file_chain_complete", not missing_result_files, "目标阶段要求的 result 文件链齐全。", severity="block" if final_stage else "warn", current="齐全" if not missing_result_files else f"缺失 {len(missing_result_files)} 个", target=", ".join(required_result_files)),
        _gate("human_reviews_recorded", bool(reviews), "已有人工/代理审核记录。", severity="warn", current=len(reviews), target=">=1"),
    ]
    blockers = [gate for gate in gates if gate["severity"] == "block" and gate["status"] != "pass"]
    next_steps_payload = workflow_next_steps_from_gate_audit(
        {
            "ok": not blockers,
            "gates": gates,
            "target_stage": target_stage,
            "question": project.question,
        }
    )
    result = {
        "schema": "research_gate_audit.v1",
        "root": str(paths["root"]),
        "question": project.question,
        "target_stage": target_stage,
        "generated_at": now_iso(),
        "gate_contract_source": GATE_CONTRACT_SOURCE,
        "ok": not blockers,
        "can_proceed": not blockers,
        "next_gate": next_steps_payload["next_gate"],
        "blockers": blockers,
        "required_result_files": required_result_files,
        "missing_result_files": missing_result_files,
        "gates": gates,
        "next_actions": _next_actions_from_gates(gates),
        "next_steps": next_steps_payload["next_steps"],
        "operator_boundary": next_steps_payload["operator_boundary"],
    }
    if write:
        write_json(paths["root"] / GATE_AUDIT_FILENAME, result)
        write_json(paths["root"] / NEXT_STEPS_FILENAME, next_steps_payload)
        (paths["notes"] / "workflow-gate-audit.md").write_text(render_gate_audit_markdown(result), encoding="utf-8")
        (paths["notes"] / "workflow-next-steps.md").write_text(render_workflow_next_steps_markdown(next_steps_payload), encoding="utf-8")
    return result


def run_multi_perspective_review(
    root: str | Path,
    *,
    perspectives: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    paths = ensure_project_dirs(root)
    project = load_project(root)
    selected = perspectives or ["事实审查", "逻辑审查", "反证审查", "可复习性审查"]
    sources = list_records(root, "sources")
    claims = list_records(root, "claims")
    evidence = list_records(root, "evidence")
    draft = draft_answer(root, include_candidate=True)
    items = [_review_for_perspective(name, sources, claims, evidence, draft) for name in selected]
    result = {
        "schema": "multi_perspective_review.v1",
        "root": str(paths["root"]),
        "question": project.question,
        "generated_at": now_iso(),
        "perspectives": items,
        "fallback_plan": _global_fallback_plan(),
        "tool_boundaries": tool_boundaries(),
        "required_artifacts": required_artifacts(),
    }
    if write:
        write_json(paths["root"] / PERSPECTIVE_REVIEW_FILENAME, result)
        (paths["notes"] / "multi-perspective-review.md").write_text(render_multi_perspective_review_markdown(result), encoding="utf-8")
        (paths["notes"] / "fallback-and-tool-boundary.md").write_text(render_fallback_and_boundary_markdown(result), encoding="utf-8")
    return result


def run_reader_persona_review(
    root: str | Path,
    *,
    personas: list[dict[str, str]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    paths = ensure_project_dirs(root)
    project = load_project(root)
    selected = personas or DEFAULT_READER_PERSONAS
    sources = list_records(root, "sources")
    claims = list_records(root, "claims")
    evidence = list_records(root, "evidence")
    draft = draft_answer(root, include_candidate=True)
    reviews = [_reader_review_for_persona(persona, sources, claims, evidence, draft) for persona in selected]
    scores = [int(item["score"]) for item in reviews]
    variance = _score_variance(scores)
    result = {
        "schema": "reader_persona_review.v1",
        "root": str(paths["root"]),
        "question": project.question,
        "generated_at": now_iso(),
        "personas": reviews,
        "score_variance": variance,
        "pass": bool(scores) and min(scores) >= 6 and variance <= 3,
        "diagnosis": _persona_diagnosis(reviews, variance),
        "revision_checklist": _persona_revision_checklist(reviews),
        "fallback_plan": [
            {"trigger": "score_variance > 3", "action": "定位不清，回到任务路由/研究框架重新判断受众和目标阶段。"},
            {"trigger": "任一 persona score < 6", "action": "不得交付最终回答；先修复该 persona 命中的阻塞点。"},
            {"trigger": "多个 persona 都指出无证据或难复习", "action": "回到 evidence/source gate，不用文字润色掩盖证据缺口。"},
        ],
    }
    if write:
        write_json(paths["root"] / PERSONA_REVIEW_FILENAME, result)
        (paths["notes"] / "reader-persona-review.md").write_text(render_reader_persona_review_markdown(result), encoding="utf-8")
    return result


def run_workflow_engine(root: str | Path, *, write: bool = True) -> dict[str, Any]:
    route = route_research_task(root, write=write)
    review = run_multi_perspective_review(root, write=write)
    persona = run_reader_persona_review(root, write=write)
    audit = audit_research_gates(root, write=write)
    return {"ok": True, "gate_contract_source": GATE_CONTRACT_SOURCE, "route": route, "review": review, "persona_review": persona, "gate_audit": audit}


def workflow_contract() -> dict[str, Any]:
    return {
        "schema": "research_workflow_contract.v1",
        "generated_at": now_iso(),
        "reference_workflow_sources": REFERENCE_WORKFLOW_SOURCES,
        "task_trigger_matrix": TASK_TRIGGER_MATRIX,
        "quality_model": {
            "research": "输出质量 = 证据覆盖度 x 来源可信度 x 可复习结构 x 人工审核闭环",
            "adapted_from": "huashu-gpt-image 三维质量模型：载体匹配度 x 精神理解深度 x 创造贡献空间",
        },
        "red_lines": [
            "未生成 result 产物文件，不得宣称对应 gate 完成。",
            "未通过 final_answer result 文件链，不得宣称可以最终交付。",
            "候选 evidence 不得自动升级为 verified evidence。",
            "来源冲突时并列展示来源质量和冲突点，不自动选择有利一方。",
            "底层搜索、抓取、视频理解、PDF OCR 优先调用已有工具，不在总控层重写。",
        ],
        "fallback_principles": [
            "三轮搜索仍找不到关键事实时 STOP，产出缺口清单。",
            "工具失败时保存失败日志和未完成状态，而不是静默跳过。",
            "如果重跑/换工具成本低于修补坏产物，优先重跑/换工具。",
            "批量产物必须留人类可扫的 review bundle/contact-sheet 式总览。",
        ],
    }


def required_artifacts() -> list[dict[str, str]]:
    return [
        {"name": "task-route.md", "purpose": "任务路由和下一步工具选择。"},
        {"name": "research-plan.md", "purpose": "知识树、搜索任务、证据目标。"},
        {"name": "workflow-gate-audit.md", "purpose": "硬闸门通过/阻塞状态。"},
        {"name": "workflow-next-steps.md", "purpose": "失败闸门转成可执行的人工/Agent 下一步任务包。"},
        {"name": "multi-perspective-review.md", "purpose": "事实、逻辑、反证、可复习性多视角审查。"},
        {"name": "reader-persona-review.md", "purpose": "不同认知距离读者的盲测和传播/可读性审查。"},
        {"name": "workflow-contract.md", "purpose": "任务类型矩阵、硬 gate 链、红线、fallback 原则。"},
        {"name": "fallback-and-tool-boundary.md", "purpose": "失败 fallback 和本地工具边界。"},
        {"name": "answer-draft.md", "purpose": "阶段性回答草稿，只汇总当前证据。"},
    ]


def tool_boundaries() -> list[dict[str, str]]:
    return [
        {"tool": "question-research-poc", "does": "总控、路由、gate、主张/证据/审核、草稿输出。", "does_not": "不复制搜索、网页抓取、视频理解、PDF OCR 底层实现。"},
        {"tool": "ai-research-workflow", "does": "搜索、深化搜索、来源候选和初步证据候选。", "does_not": "不替代本项目的人工质量标注和最终证据审核。"},
        {"tool": "web-content-fetcher", "does": "网页抓取、正文抽取、raw/extracted/archive 留存。", "does_not": "不做研究判断，不自动认定证据支持关系。"},
        {"tool": "video-knowledge-pipeline", "does": "知识类视频 ASR、抽帧、OCR、多模态/时序理解、review bundle。", "does_not": "不承担跨来源研究结论和问题框架。"},
        {"tool": "ebook_markdown_pipeline / bookwiki", "does": "PDF、电子书、扫描页和图文型材料解析。", "does_not": "不处理非图文型视频画面语义。"},
    ]


def render_task_route_markdown(route: dict[str, Any]) -> str:
    lines = _frontmatter(route.get("question", ""), "task-route")
    lines.extend(
        [
            f"# 任务路由：{route.get('question', '')}",
            "",
            f"- 路径：`{route.get('route', '')}`",
            f"- 原因：{route.get('reason', '')}",
            "",
            "## 下一步工具",
            "",
        ]
    )
    lines.extend(f"- {tool}" for tool in route.get("next_tools", []))
    lines.extend(["", "## 硬闸门", ""])
    lines.extend(f"- `{gate.get('id')}`：{gate.get('description')}" for gate in route.get("hard_gates", []))
    lines.extend(["", "## 必须 result 文件", ""])
    lines.extend(f"- `{item}`" for item in route.get("required_result_files", []))
    lines.extend(["", "## 失败 Fallback", ""])
    lines.extend(f"- {item}" for item in route.get("fallback_plan", []))
    return "\n".join(lines).rstrip() + "\n"


def render_gate_audit_markdown(audit: dict[str, Any]) -> str:
    lines = _frontmatter(audit.get("question", ""), "gate-audit")
    lines.extend(
        [
            f"# Gate 审计：{audit.get('question', '')}",
            "",
            f"- 目标阶段：`{audit.get('target_stage', '')}`",
            f"- 是否可进入下一阶段：`{audit.get('can_proceed')}`",
            f"- 下一关口：{audit.get('next_gate', '')}",
            f"- Gate 契约：{audit.get('gate_contract_source', {}).get('pattern', '')}",
            "",
            "## Gate 状态",
            "",
        ]
    )
    for gate in audit.get("gates", []):
        lines.append(
            f"- [{'x' if gate.get('ok') else ' '}] `{gate.get('severity')}` / `{gate.get('id')}`："
            f"{gate.get('description')}（{gate.get('current')} / {gate.get('target')}）"
        )
    lines.extend(["", "## 下一步", ""])
    lines.extend(f"- {item}" for item in audit.get("next_actions", [])) if audit.get("next_actions") else lines.append("- 当前没有阻塞项。")
    return "\n".join(lines).rstrip() + "\n"


def render_workflow_contract_markdown(contract: dict[str, Any]) -> str:
    lines = _frontmatter("问题主导研究总控流程", "workflow-contract")
    lines.extend(["# 总控流程契约", "", "## 任务类型矩阵", ""])
    for row in contract.get("task_trigger_matrix", []):
        lines.append(f"- `{row.get('id')}` -> `{row.get('route')}`")
        lines.append(f"  - signals: {', '.join(row.get('signals', []))}")
        lines.append(f"  - gates: {', '.join(row.get('hard_gate_chain', []))}")
        lines.append(f"  - result files: {', '.join(row.get('result_files', []))}")
    lines.extend(["", "## 红线", ""])
    lines.extend(f"- {item}" for item in contract.get("red_lines", []))
    lines.extend(["", "## Fallback 原则", ""])
    lines.extend(f"- {item}" for item in contract.get("fallback_principles", []))
    return "\n".join(lines).rstrip() + "\n"


def workflow_next_steps_from_gate_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Turn failed research gates into ordered operator tasks.

    This mirrors the domain-neutral contract used by ai-content-acquisition-pilot:
    failed gates become ordered steps with human action, agent action, entrypoints,
    and execution boundaries.
    """
    steps: list[dict[str, Any]] = []
    gates = audit.get("gates", [])
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict) or gate.get("ok"):
                continue
            gate_id = str(gate.get("id", ""))
            rule = GATE_NEXT_STEP_RULES.get(gate_id, {})
            steps.append(
                {
                    "order": len(steps) + 1,
                    "gate_id": gate_id,
                    "gate_title": gate.get("title", gate.get("description", "")),
                    "severity": gate.get("severity", "block"),
                    "current": gate.get("current", ""),
                    "target": gate.get("target", ""),
                    "blockers": gate.get("blockers", []),
                    "human_action": rule.get("human_action", gate.get("next_gate", "")),
                    "agent_action": rule.get("agent_action", gate.get("next_gate", "")),
                    "can_agent_execute": bool(rule.get("can_agent_execute", False)),
                    "requires_human_confirmation": bool(rule.get("requires_human_confirmation", True)),
                    "entrypoints": {
                        "cli": rule.get("cli", []),
                        "mcp": rule.get("mcp", []),
                        "ui": rule.get("ui", []),
                    },
                }
            )
    return {
        "schema": "research_workflow_next_steps.v1",
        "gate_contract_source": GATE_CONTRACT_SOURCE,
        "purpose": "把失败闸门转成可执行的下一步任务包。",
        "ok": bool(audit.get("ok", audit.get("can_proceed", False))),
        "source_gate": "research-gate-audit",
        "target_stage": audit.get("target_stage", "answer_draft"),
        "question": audit.get("question", ""),
        "step_count": len(steps),
        "next_gate": steps[0]["human_action"] if steps else "当前无失败闸门，可以进入人工验收或阶段性输出。",
        "next_steps": steps,
        "operator_boundary": [
            "Agent 可以生成路线、计划、候选证据、审查包和下一步任务包。",
            "Agent 不得把候选证据自动升级为 verified evidence。",
            "来源质量、证据可信度、最终结论强度必须保留人工审核位置。",
            "Logseq 写回必须经过 WebUI/审核包人工确认，不允许绕过审核直接写入。",
        ],
    }


def render_workflow_next_steps_markdown(payload: dict[str, Any]) -> str:
    lines = _frontmatter(str(payload.get("question", "")), "workflow-next-steps")
    lines.extend(
        [
            f"# 流程下一步任务包：{payload.get('question', '')}",
            "",
            f"- 来源闸门：{payload.get('source_gate', '')}",
            f"- 下一关口：{payload.get('next_gate', '')}",
            f"- Gate 契约：{payload.get('gate_contract_source', {}).get('pattern', '')}",
            "",
            "## 下一步",
            "",
        ]
    )
    steps = payload.get("next_steps", [])
    if isinstance(steps, list) and steps:
        for step in steps:
            if not isinstance(step, dict):
                continue
            lines.append(f"{step.get('order')}. {step.get('gate_title')}：{step.get('current')} / {step.get('target')}")
            lines.append(f"   - 人工动作：{step.get('human_action')}")
            lines.append(f"   - Agent 动作：{step.get('agent_action')}")
            lines.append(f"   - 可由 Agent 执行：{'是' if step.get('can_agent_execute') else '否'}")
    else:
        lines.append("- 当前无失败闸门，可以进入人工验收或阶段性输出。")
    lines.extend(["", "## 操作边界", ""])
    lines.extend(f"- {item}" for item in payload.get("operator_boundary", []))
    return "\n".join(lines).rstrip() + "\n"


def render_multi_perspective_review_markdown(review: dict[str, Any]) -> str:
    lines = _frontmatter(review.get("question", ""), "multi-perspective-review")
    lines.extend([f"# 多视角审查：{review.get('question', '')}", ""])
    for item in review.get("perspectives", []):
        lines.extend([f"## {item.get('perspective', '')}", ""])
        lines.extend(f"- {finding}" for finding in item.get("findings", []))
        lines.extend(["", "### 修改决策", ""])
        lines.extend(f"- {decision}" for decision in item.get("decisions", []))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_reader_persona_review_markdown(review: dict[str, Any]) -> str:
    lines = _frontmatter(review.get("question", ""), "reader-persona-review")
    lines.extend(
        [
            f"# Reader Persona 盲测：{review.get('question', '')}",
            "",
            f"- 是否通过：`{review.get('pass')}`",
            f"- 分数方差：`{review.get('score_variance')}`",
            f"- 综合诊断：{review.get('diagnosis', '')}",
            "",
            "## Persona 结果",
            "",
        ]
    )
    for item in review.get("personas", []):
        lines.append(f"## {item.get('name')}（{item.get('distance')}）")
        lines.append(f"- score: {item.get('score')}/10")
        lines.append(f"- focus: {item.get('focus')}")
        lines.append(f"- verdict: {item.get('verdict')}")
        lines.extend(f"- 命中问题：{issue}" for issue in item.get("issues", []))
        lines.append("")
    lines.extend(["## 修改清单", ""])
    lines.extend(f"- {item}" for item in review.get("revision_checklist", []))
    lines.extend(["", "## Fallback", ""])
    for item in review.get("fallback_plan", []):
        lines.append(f"- **{item.get('trigger')}**：{item.get('action')}")
    return "\n".join(lines).rstrip() + "\n"


def render_fallback_and_boundary_markdown(review: dict[str, Any]) -> str:
    lines = _frontmatter(review.get("question", ""), "fallback-tool-boundary")
    lines.extend([f"# Fallback 与工具边界：{review.get('question', '')}", "", "## 失败 Fallback", ""])
    for item in review.get("fallback_plan", []):
        lines.append(f"- **{item.get('trigger', '')}**：{item.get('action', '')}")
    lines.extend(["", "## 工具边界", ""])
    for item in review.get("tool_boundaries", []):
        lines.append(f"- **{item.get('tool', '')}**：做 {item.get('does', '')}；不做 {item.get('does_not', '')}")
    lines.extend(["", "## 必须产物", ""])
    for item in review.get("required_artifacts", []):
        lines.append(f"- `{item.get('name', '')}`：{item.get('purpose', '')}")
    return "\n".join(lines).rstrip() + "\n"


def _review_for_perspective(name: str, sources: list[dict[str, Any]], claims: list[dict[str, Any]], evidence: list[dict[str, Any]], draft: str) -> dict[str, Any]:
    if name == "事实审查":
        findings = [
            f"来源数量：{len(sources)}；其中未标注质量：{len([s for s in sources if s.get('quality') == 'unknown'])}。",
            "所有数字、时间、产品名必须回到 source/evidence 文件核对，不能只信草稿文字。",
        ]
        decisions = ["质量为 unknown 的来源不得作为强结论依据。", "事实争议处保留不确定性，不做单边结论。"]
    elif name == "逻辑审查":
        unsupported = [claim for claim in claims if not any(row.get("claim_id") == claim.get("id") for row in evidence)]
        findings = [f"无证据主张数量：{len(unsupported)}。", "主张与证据必须逐条连接，不能用来源存在替代证据支持。"]
        decisions = ["无证据主张只保留为待验证问题。", "草稿中每个强判断必须能追到 evidence_id。"]
    elif name == "反证审查":
        contradictions = [row for row in evidence if row.get("relation") == "contradicts"]
        findings = [f"反证证据数量：{len(contradictions)}。", "如果没有反证，不能说明没有争议，只说明反证检查不足。"]
        decisions = ["进入最终结论前必须至少安排 counter-evidence search。", "反证和限制条件在草稿中单独列出。"]
    else:
        findings = [f"当前草稿长度：{len(draft)} 字符。", "输出应能被人类复习：有主张、证据、来源质量、缺口，而不是散文式总结。"]
        decisions = ["保留 evidence card 和 overview，不只交付最终回答。", "缺口明确列在草稿或 gate audit 中。"]
    return {"perspective": name, "findings": findings, "decisions": decisions}


def _reader_review_for_persona(persona: dict[str, str], sources: list[dict[str, Any]], claims: list[dict[str, Any]], evidence: list[dict[str, Any]], draft: str) -> dict[str, Any]:
    issues: list[str] = []
    score = 8
    if not sources:
        issues.append("没有来源，读者无法判断可信度。")
        score -= 2
    if claims and not evidence:
        issues.append("有主张但没有证据卡，像观点清单而不是研究产物。")
        score -= 2
    if evidence and not any(row.get("status") == "verified" for row in evidence):
        issues.append("证据尚未 verified，只能作为候选结论。")
        score -= 2
    if "复习" in persona.get("name", "") and "##" not in draft:
        issues.append("结构层级不足，不利于复习和检索。")
        score -= 1
    if persona.get("id") == "skeptic" and not any(row.get("relation") == "contradicts" for row in evidence):
        issues.append("缺少明确反证或限制条件，怀疑型读者不会买账。")
        score -= 1
    verdict = "可以作为阶段性材料" if score >= 6 else "不得作为最终交付"
    return {
        "id": persona.get("id", ""),
        "name": persona.get("name", ""),
        "distance": persona.get("distance", ""),
        "focus": persona.get("focus", ""),
        "score": max(score, 1),
        "verdict": verdict,
        "issues": issues or ["未发现该 persona 视角下的硬阻塞。"],
    }


def _score_variance(scores: list[int]) -> float:
    if not scores:
        return 0.0
    mean = sum(scores) / len(scores)
    return round(sum((score - mean) ** 2 for score in scores) / len(scores), 2)


def _persona_diagnosis(reviews: list[dict[str, Any]], variance: float) -> str:
    low = [item for item in reviews if int(item.get("score", 0)) < 6]
    if variance > 3:
        return "不同读者评分分裂明显，说明定位或结构不清。"
    if low:
        return "存在低分 persona，当前只适合阶段性材料，不适合最终交付。"
    return "读者盲测未发现硬阻塞，仍需结合证据 gate 判断能否交付。"


def _persona_revision_checklist(reviews: list[dict[str, Any]]) -> list[str]:
    checklist: list[str] = []
    for item in reviews:
        for issue in item.get("issues", []):
            if issue != "未发现该 persona 视角下的硬阻塞。":
                checklist.append(f"{item.get('name')}：{issue}")
    return checklist or ["当前无 persona 命中的硬阻塞，保留人工终审。"]


def _gate(gate_id: str, passed: bool, description: str, *, severity: str = "block", current: Any = "", target: Any = "") -> dict[str, Any]:
    rule = GATE_NEXT_STEP_RULES.get(gate_id, {})
    next_gate = str(rule.get("human_action") or rule.get("agent_action") or description)
    return {
        "id": gate_id,
        "title": description.rstrip("。"),
        "ok": passed,
        "status": "pass" if passed else "fail",
        "severity": severity,
        "description": description,
        "current": current,
        "target": target,
        "next_gate": next_gate,
        "blockers": [] if passed else [next_gate],
    }


def _next_actions_from_gates(gates: list[dict[str, Any]]) -> list[str]:
    mapping = {
        "task_route_present": "运行 route-research-task 生成任务路由。",
        "research_plan_present": "运行 plan-research --add-claims 生成研究计划和初始主张。",
        "sources_present": "通过 research-search 或 add-source 导入来源。",
        "source_quality_reviewed": "在 UI 或 CLI 中标注所有来源质量。",
        "claims_present": "从研究计划或人工判断写入可验证主张。",
        "evidence_present": "抓取正文或导入搜索结果后创建证据卡。",
        "verified_evidence_present": "人工审核 evidence，将可信证据标为 verified。",
        "counter_evidence_checked": "运行反证搜索或补充 contradicts/context 证据。",
        "multi_perspective_review_present": "运行 multi-perspective-review 生成审查文件。",
        "reader_persona_review_present": "运行 reader-persona-review 生成读者盲测文件。",
        "result_file_chain_complete": "补齐目标阶段要求的 result 文件链。",
        "human_reviews_recorded": "至少记录一次来源或证据审核。",
    }
    return [mapping.get(gate["id"], gate["description"]) for gate in gates if gate["status"] != "pass" and gate["id"] in mapping]


def _hard_gates_for_route(route: str) -> list[dict[str, str]]:
    common = [
        {"id": "route_written", "description": "必须保存 task-route.md/json。"},
        {"id": "tool_boundary_checked", "description": "必须确认调用哪个现有工具，不复制底层实现。"},
    ]
    route_specific = {
        "quick_answer": [{"id": "verified_evidence_present", "description": "至少一条 verified evidence。"}],
        "deep_research": [{"id": "research_plan_present", "description": "先有研究计划和搜索任务。"}, {"id": "counter_evidence_checked", "description": "必须安排反证检查。"}],
        "source_ingest": [{"id": "source_artifact_written", "description": "必须保存抓取 JSON/Markdown。"}],
        "video_knowledge_ingest": [{"id": "video_bundle_written", "description": "必须保留视频转写、关键帧/帧组和 review bundle。"}],
        "final_answer_review": [{"id": "multi_perspective_review_present", "description": "必须有 multi-perspective-review.md/json。"}, {"id": "reader_persona_review_present", "description": "必须有 reader-persona-review.md/json。"}, {"id": "result_file_chain_complete", "description": "必须补齐目标阶段 result 文件链。"}],
    }
    return common + route_specific.get(route, [])


def _fallback_plan_for_route(route: str) -> list[str]:
    if route == "video_knowledge_ingest":
        return ["视频下载失败时先登记为 video source，不强行处理。", "ASR 不可用时保留音频/字幕缺口，改走人工转写或云端 API 计划。", "多模态 API 不可用时先生成 frame group 和人工审核 bundle。"]
    if route == "source_ingest":
        return ["网页抓取失败时保留 source 记录和失败日志。", "普通抓取失败再尝试授权浏览器低频抓取。", "仍失败时记录为 source gap，不编造正文。"]
    if route == "quick_answer":
        return ["证据不足时降级为阶段性回答。", "无 verified evidence 时阻止正式结论，只输出缺口清单。"]
    if route == "final_answer_review":
        return ["result 文件链缺失时 block 最终交付。", "persona 评分分裂时回到任务路由和研究框架，不靠润色硬发。", "人工审核缺失时只输出阶段性材料。"]
    return ["搜索服务不可用时保存 search task，等待 ai-research-workflow 启动。", "搜索结果冲突时并列展示，不自动裁决。", "证据不足时停止在 gate audit，不生成强结论。"]


def _global_fallback_plan() -> list[dict[str, str]]:
    return [
        {"trigger": "搜索服务不可用", "action": "保存 search task 和 gate audit；提示启动 ai-research-workflow，不编造来源。"},
        {"trigger": "网页抓取失败", "action": "保留 source 记录和失败日志；尝试 browser fetch；仍失败则进入 source gap。"},
        {"trigger": "视频处理失败", "action": "保留视频 source、下载路径和未完成步骤；改由 video-knowledge-pipeline 继续。"},
        {"trigger": "证据冲突", "action": "并列展示冲突来源、质量和摘录，等待人工判断。"},
        {"trigger": "gate 未通过", "action": "阻止进入目标阶段，只输出下一步行动清单。"},
        {"trigger": "result 文件链缺失", "action": "不得宣称完成；运行对应 review 工具补齐产物。"},
        {"trigger": "读者盲测分裂", "action": "回到任务路由和受众定义，不直接润色。"},
    ]


def _task_type_from_text(text: str) -> str:
    for row in TASK_TRIGGER_MATRIX:
        if any(signal.lower() in text for signal in row["signals"]):
            return str(row["id"])
    return "new_research"


def _trigger_matrix_for_route(route: str) -> dict[str, Any]:
    for row in TASK_TRIGGER_MATRIX:
        if row.get("route") == route:
            return row
    return {}


def _required_result_files_for_route(route: str) -> list[str]:
    row = _trigger_matrix_for_route(route)
    return [str(item) for item in row.get("result_files", [])] if row else ["task-route.md", "workflow-gate-audit.md"]


def _required_result_files_for_stage(target_stage: str) -> list[str]:
    if target_stage in {"final_answer", "publish", "delivery"}:
        return ["task-route.md", "research-plan.md", "workflow-gate-audit.md", "workflow-next-steps.md", "multi-perspective-review.md", "reader-persona-review.md", "fallback-and-tool-boundary.md"]
    return ["task-route.md", "workflow-gate-audit.md"]


def _missing_note_files(notes_dir: Path, filenames: list[str]) -> list[str]:
    return [name for name in filenames if not (notes_dir / name).exists()]


def _has_counter_search(plan_path: Path) -> bool:
    if not plan_path.exists():
        return False
    try:
        import json

        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any("counter" in str(task.get("id", "")) or "反证" in str(task.get("intent", "")) for task in data.get("search_tasks", []))


def _looks_like_video(text: str, sources: list[dict[str, Any]]) -> bool:
    return any(word in text for word in ["视频", "课程", "讲课", "讲解", "bilibili", "youtube", ".mp4"]) or any(source.get("source_type") == "video" for source in sources)


def _looks_like_source_ingest(text: str, sources: list[dict[str, Any]]) -> bool:
    return any(word in text for word in ["http://", "https://", "网页", "pdf", "文档", "资料"]) or any(source.get("url") or source.get("path") for source in sources)


def _frontmatter(question: str, tag: str) -> list[str]:
    return ["---", "type: note", f'title: "{question} - {tag}"', f"tags: [ai-research, {tag}]", "status: active", f"created: {now_iso()}", "---", ""]
