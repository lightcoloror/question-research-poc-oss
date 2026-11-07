from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import dataclass_to_dict, now_iso, project_paths
from .orchestrator import add_claim, list_records
from .storage import ensure_project_dirs, load_project, write_json


PLAN_FILENAME = "research-plan.json"


def build_research_plan(
    root: str | Path,
    *,
    question: str | None = None,
    write: bool = True,
    add_claims: bool = False,
) -> dict[str, Any]:
    """Build a deterministic question-led research plan.

    This is intentionally model-free: it gives the controller a stable first pass
    that a human or agent can edit before dispatching search/deepen tools.
    """
    paths = ensure_project_dirs(root)
    project_question = question or load_project(root).question
    subquestions = _subquestions(project_question)
    seed_claims = _seed_claims(project_question, subquestions)
    existing_claim_texts = {str(row.get("text", "")).strip() for row in list_records(root, "claims")}
    added_claims = []
    if add_claims:
        for claim in seed_claims:
            text = claim["text"].strip()
            if text and text not in existing_claim_texts:
                added_claims.append(dataclass_to_dict(add_claim(root, text=text, notes=claim["notes"])))
                existing_claim_texts.add(text)

    plan = {
        "schema": "question_research_plan.v1",
        "root": str(paths["root"]),
        "question": project_question,
        "generated_at": now_iso(),
        "subquestions": subquestions,
        "seed_claims": seed_claims,
        "search_tasks": _search_tasks(project_question, subquestions),
        "evidence_targets": _evidence_targets(project_question),
        "tool_plan": _tool_plan(),
        "review_queue": [
            {"kind": "source_quality", "instruction": "人工标注来源质量：good/mixed/poor，并说明原因。"},
            {"kind": "claim_check", "instruction": "把开放主张改写成可被证据支持或反驳的表达。"},
            {"kind": "evidence_review", "instruction": "证据入库后审核 relation、confidence 和是否保留。"},
        ],
        "added_claims": added_claims,
    }
    if write:
        write_json(paths["root"] / PLAN_FILENAME, plan)
        (paths["notes"] / "research-plan.md").write_text(render_research_plan_markdown(plan), encoding="utf-8")
    return plan


def read_research_plan(root: str | Path) -> dict[str, Any]:
    path = project_paths(root)["root"] / PLAN_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"research plan not found: {path}")
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("research plan must be a JSON object")
    return data


def render_research_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "---",
        "type: note",
        f'title: "{plan.get("question", "")} - 研究计划"',
        "tags: [ai-research, research-plan]",
        "status: active",
        f"created: {now_iso()}",
        "---",
        "",
        f"# 研究计划：{plan.get('question', '')}",
        "",
        "## 子问题",
        "",
    ]
    for item in plan.get("subquestions", []):
        lines.append(f"- **{item.get('title', '')}**：{item.get('question', '')}")
    lines.extend(["", "## 初始主张", ""])
    for item in plan.get("seed_claims", []):
        lines.append(f"- {item.get('text', '')}")
    lines.extend(["", "## 搜索任务", ""])
    for item in plan.get("search_tasks", []):
        lines.append(f"- `{item.get('priority', '')}` {item.get('query', '')}")
    lines.extend(["", "## 工具分工", ""])
    for item in plan.get("tool_plan", []):
        lines.append(f"- **{item.get('tool', '')}**：{item.get('use_for', '')}")
    return "\n".join(lines).rstrip() + "\n"


def _subquestions(question: str) -> list[dict[str, str]]:
    templates = [
        ("定义与边界", "这个问题里的关键概念、适用范围和排除范围是什么？"),
        ("现有事实与背景", "目前有哪些已知事实、时间线、上下文和基础材料？"),
        ("机制与因果链", "如果这个判断成立，它背后的机制、因果链或工作流程是什么？"),
        ("证据与反证", "哪些证据支持它？哪些证据反驳它？证据质量分别如何？"),
        ("实践路径与案例", "已有工具、案例、实践路径分别能解决哪一部分？"),
        ("风险与限制", "这个方向有哪些失效条件、成本、争议和人工审核点？"),
    ]
    return [
        {
            "id": f"sq_{index:02d}",
            "title": title,
            "question": f"围绕「{question}」，{body}",
        }
        for index, (title, body) in enumerate(templates, start=1)
    ]


def _seed_claims(question: str, subquestions: list[dict[str, str]]) -> list[dict[str, str]]:
    claims = [
        f"「{question}」需要先明确概念边界，否则后续证据会混用不同定义。",
        f"「{question}」至少需要同时收集支持证据和反证，不能只按单一路径搜索。",
        f"「{question}」的阶段性结论必须标注证据质量和人工审核状态。",
    ]
    for item in subquestions[:3]:
        claims.append(f"{item['title']} 是回答「{question}」时需要单独验证的子问题。")
    return [{"text": text, "notes": "由研究计划模块生成，需人工或代理继续验证。"} for text in claims]


def _search_tasks(question: str, subquestions: list[dict[str, str]]) -> list[dict[str, Any]]:
    tasks = [
        {
            "id": "search_primary",
            "priority": "P0",
            "query": question,
            "intent": "先收集通用背景、主要观点和高质量来源。",
            "tool": "ai-research-workflow",
        }
    ]
    for item in subquestions:
        tasks.append(
            {
                "id": f"search_{item['id']}",
                "priority": "P1",
                "query": f"{question} {item['title']}",
                "intent": item["question"],
                "tool": "ai-research-workflow",
            }
        )
    tasks.append(
        {
            "id": "search_counter_evidence",
            "priority": "P1",
            "query": f"{question} 反对 争议 限制 失败 案例",
            "intent": "专门寻找反证、限制条件和失败案例。",
            "tool": "ai-research-workflow",
        }
    )
    return tasks


def _evidence_targets(question: str) -> list[dict[str, str]]:
    return [
        {"kind": "primary_source", "target": f"围绕「{question}」的官方文档、原始发布、演讲、论文或一手材料。"},
        {"kind": "quality_review", "target": "来源质量标注：作者/机构、日期、方法、是否可复核、是否有利益相关。"},
        {"kind": "case", "target": "真实案例、项目、工具实测结果，而不是只收集观点文章。"},
        {"kind": "counter_evidence", "target": "反例、失败条件、批评观点和不确定性。"},
    ]


def _tool_plan() -> list[dict[str, str]]:
    return [
        {"tool": "question-research-poc", "use_for": "总控项目、主张、证据、审核、图谱候选和阶段性输出。"},
        {"tool": "ai-research-workflow", "use_for": "多元搜索、深化搜索、来源候选和初步证据候选。"},
        {"tool": "web-content-fetcher", "use_for": "对指定 URL 抓取正文，补足可引用原文。"},
        {"tool": "video-knowledge-pipeline", "use_for": "知识类视频全量转结构化资料，再作为视频来源入库。"},
        {"tool": "bookwiki / ebook_markdown_pipeline", "use_for": "PDF、电子书、扫描页和图文型材料解析。"},
        {"tool": "Obsidian", "use_for": "长期资料库、人工阅读、复习和跨项目积累。"},
    ]
