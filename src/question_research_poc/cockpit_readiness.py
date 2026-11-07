from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_manifest import build_agent_manifest
from .runtime_config import RUNTIME_CONFIG_PATH


READINESS_SCHEMA = "question_research_cockpit_readiness.v1"


def audit_cockpit_readiness(root: str | Path | None = None) -> dict[str, Any]:
    """Audit whether the controller has the cockpit capabilities promised by the roadmap."""
    from .mcp_server import list_mcp_tools

    repo = Path(__file__).resolve().parents[2]
    manifest = build_agent_manifest(root)
    action_ids = {str(item.get("id", "")) for item in manifest.get("ui_actions", [])}
    artifact_ids = {str(item.get("artifact", "")) for item in manifest.get("read_artifact_endpoints", [])}
    mcp_names = {str(item.get("name", "")) for item in list_mcp_tools()}
    web_app = _read(repo / "src" / "question_research_poc" / "web_app.py")
    app_js = _read(repo / "web" / "app.js")
    index_html = _read(repo / "web" / "index.html")

    sections = [
        _section(
            "runtime_config",
            "统一 runtime config",
            [
                _check("runtime_config_exists", RUNTIME_CONFIG_PATH.exists(), str(RUNTIME_CONFIG_PATH)),
                _check("run_web_reads_runtime_config", "run-web" in _read(repo / "src" / "question_research_poc" / "cli.py") and "web_port" in web_app, "WebUI starts from config/runtime.json"),
            ],
        ),
        _section(
            "gate_workbench",
            "Gate 工作台",
            [
                _check("workflow_gate_details_payload", "gate_details" in web_app and "build_gate_details" in _read(repo / "src" / "question_research_poc" / "review_state.py"), "workflow.gate_details"),
                _check("gate_detail_ui", "function renderGateDetails" in app_js and 'id="gateDetailRows"' in index_html, "Clickable Gate detail panel"),
                _check("gate_detail_agent_interfaces", {"get_gate_details", "audit_research_gates", "run_next_step"}.issubset(mcp_names), "MCP gate tools"),
            ],
        ),
        _section(
            "review_queue",
            "人工审核队列",
            [
                _check("review_queue_payload", "build_review_queue" in web_app and "get_review_queue" in mcp_names, "Review queue API/MCP"),
                _check("source_quality_review_action", "data-source-review-apply" in app_js and "review_source" in mcp_names, "Inline source review"),
                _check("evidence_review_action", "data-evidence-review-apply" in app_js and "review_evidence" in mcp_names, "Inline evidence review"),
                _check("claim_focus_action", "data-queue-claim-id" in app_js, "Claim-to-evidence focus"),
            ],
        ),
        _section(
            "external_tool_bridge",
            "外部工具桥接工作台",
            [
                _check("ai_research_bridge", {"plan_ai_research_search", "run_ai_research_search", "import_ai_research_result"}.issubset(mcp_names), "ai-research-workflow bridge"),
                _check("web_fetch_bridge", {"plan_fetch_source_content", "fetch_source_content"}.issubset(mcp_names), "web-content-fetcher bridge"),
                _check("video_bridge", {"plan_video_knowledge_run", "import_video_knowledge_artifacts", "run_video_knowledge_tool"}.issubset(mcp_names), "video-knowledge-pipeline bridge"),
                _check("tool_bridge_status", "get_tool_bridge_status" in mcp_names and "renderToolBridgeStatus" in app_js, "Read-only bridge status"),
            ],
        ),
        _section(
            "project_overview",
            "研究项目总览页",
            [
                _check("overview_payload", "get_project_overview" in mcp_names and "project_overview" in artifact_ids, "Structured overview"),
                _check("overview_ui_metrics", all(text in app_js for text in ("renderDashboard", "renderProjectOverview", "claimCoverage", "sourceQualityRows")), "Dashboard metrics"),
            ],
        ),
        _section(
            "agent_interfaces",
            "CLI / MCP 对齐",
            [
                _check("required_agent_tools", {"get_project_status", "get_gate_details", "get_review_queue", "run_next_step", "read_workflow_artifact"}.issubset(mcp_names), "Required MCP tools"),
                _check("manifest_maps_actions", {"review_source", "review_evidence", "run_work_queue_item", "export_final_answer"}.issubset(action_ids), "Manifest action map"),
                _check("human_boundaries_documented", len(manifest.get("human_review_boundaries", [])) >= 5 and len(manifest.get("forbidden_operations", [])) >= 5, "Review and forbidden boundaries"),
            ],
        ),
        _section(
            "knowledge_base_output",
            "Obsidian / Logseq 输出",
            [
                _check("obsidian_review_pack", "export_research_pack_to_obsidian" in mcp_names, "Obsidian Markdown review pack"),
                _check("logseq_review_handoff", "create_logseq_review_handoff" in mcp_names, "Logseq review handoff"),
                _check("final_answer_guard", "export_final_answer" in mcp_names and "audit_completeness" in mcp_names, "Guarded final answer export"),
            ],
        ),
        _section(
            "regression_confidence",
            "可复现验证",
            [
                _check("demo_project", "build_demo_project" in mcp_names, "Deterministic demo project"),
                _check("webui_smoke", (repo / "scripts" / "smoke-webui.ps1").exists(), "WebUI smoke script"),
            ],
        ),
    ]
    passed = sum(1 for section in sections for check in section["checks"] if check["ok"])
    total = sum(len(section["checks"]) for section in sections)
    return {
        "ok": passed == total,
        "schema": READINESS_SCHEMA,
        "root": str(root or ""),
        "runtime_config": str(RUNTIME_CONFIG_PATH),
        "summary": {
            "passed": passed,
            "total": total,
            "percent": round((passed / total) * 100, 1) if total else 0,
        },
        "sections": sections,
        "remaining_gaps": [check for section in sections for check in section["checks"] if not check["ok"]],
        "next_actions": _next_actions(sections),
    }


def _section(section_id: str, title: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for check in checks if check["ok"])
    return {
        "id": section_id,
        "title": title,
        "status": "pass" if passed == len(checks) else "partial" if passed else "missing",
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }


def _check(check_id: str, ok: bool, evidence: str) -> dict[str, Any]:
    return {"id": check_id, "ok": bool(ok), "evidence": evidence}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _next_actions(sections: list[dict[str, Any]]) -> list[str]:
    actions = []
    for section in sections:
        missing = [check for check in section["checks"] if not check["ok"]]
        if missing:
            actions.append(f"补齐 {section['title']}：{', '.join(check['id'] for check in missing)}")
    return actions or ["总控层核心闭环已具备；下一步可以继续增强外部工具桥接质量和真实项目使用体验。"]
