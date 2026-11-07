from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from .ai_research_bridge import ai_research_status, import_ai_research_result, plan_ai_research_search, run_ai_research_search
from .agent_interface import get_gate_details, get_project_dashboard, get_project_overview, get_project_status, get_review_queue, get_tool_health_dashboard, read_workflow_artifact, run_next_step
from .agent_manifest import build_agent_manifest
from .agent_runbook import build_agent_runbook
from .bridge_actions import enqueue_bridge_actions, plan_bridge_action, run_bridge_action
from .bridge_runs import list_bridge_runs, read_bridge_run, retry_bridge_run_plan
from .cockpit_readiness import audit_cockpit_readiness
from .completeness_audit import audit_research_completeness
from .demo_project import build_demo_project
from .external_researcher_bridge import (
    answer_external_researcher_followup,
    check_external_researcher_automation_profiles,
    export_external_researcher_bundle,
    import_external_researcher_report,
    list_external_researcher_reports,
    plan_external_researcher_automation,
    plan_external_researcher_session,
    prepare_external_researcher_login_profiles,
    run_external_researcher_automation,
    write_external_researcher_profile_template,
)
from .omnigent_poc import run_omnigent_external_research_poc
from .final_answer import export_final_answer
from .graph_candidates import export_reviewed_graph, generate_graph_candidates, list_graph_candidates, review_graph_candidate
from .guarded_e2e_fixture import run_guarded_e2e_fixture
from .orchestrator import (
    add_claim,
    add_evidence,
    add_source,
    add_video,
    draft_answer,
    export_obsidian,
    import_sources,
    init_project,
    list_records,
    render_project_overview,
    review_evidence,
    review_graph_edge,
    review_source,
    write_graph_csv,
)
from .research_plan import build_research_plan, read_research_plan
from .research_gaps import analyze_research_gaps
from .research_loop import export_research_loop_review_pack, list_research_loops, read_research_loop, run_research_loop
from .research_output import export_research_output
from .research_pack import create_logseq_review_handoff, export_research_pack, export_research_pack_to_obsidian
from .source_inbox import add_inbox_item, get_source_inbox, import_inbox_item_as_source, reject_inbox_item
from .sync_safety import audit_sync_safety
from .tool_bridge_status import build_tool_bridge_status
from .tool_executor import run_local_tool_action
from .vane_perplexica_bridge import import_vane_perplexica_result, plan_vane_perplexica_search, run_vane_perplexica_search, vane_perplexica_status
from .video_artifact_import import import_video_knowledge_artifacts
from .video_knowledge_bridge import check_video_run_artifacts, plan_video_knowledge_run, run_video_knowledge_tool
from .web_fetch_bridge import fetch_source_content, plan_fetch_source_content
from .work_queue import enqueue_runbook_tasks, get_work_queue, run_work_queue_item, update_task_status
from .workflow_engine import audit_research_gates, route_research_task, run_multi_perspective_review, run_reader_persona_review, run_workflow_engine


def _tool_schema(name: str, required: list[str], optional: list[str] | None = None) -> dict[str, Any]:
    properties = {key: {"type": "string"} for key in required + (optional or [])}
    if "include_candidate" in properties:
        properties["include_candidate"] = {"type": "boolean", "default": False}
    for key in ("write", "add_claims", "deep", "no_network", "fetch", "import_results", "import_sources", "import_claims", "import_evidence", "use_browser", "include_raw", "import_source", "import_as_source", "create_candidate_evidence", "build_initial_bundle", "execute", "headless", "dry_run", "live"):
        if key in properties:
            properties[key] = {"type": "boolean"}
    for key in ("max_results", "timeout_seconds", "auto_after_seconds", "max_frames", "limit", "keep_open_seconds", "rounds", "max_queries_per_round", "status_timeout_seconds"):
        if key in properties:
            properties[key] = {"type": "integer"}
    if "args" in properties:
        properties["args"] = {"type": "object"}
    return {"name": name, "description": f"question-research-poc {name}", "inputSchema": {"type": "object", "required": required, "properties": properties}}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "run_video_knowledge_tool",
        "description": "Bridge to the extracted video-knowledge-pipeline CLI. Use this for video ASR, frame routing, OCR/document screenshot parsing, multimodal frame analysis, temporal frame analysis, and WebUI bundle work.",
        "inputSchema": {
            "type": "object",
            "required": ["args"],
            "properties": {
                "args": {"type": "array", "items": {"type": "string"}},
                "root": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 0},
            },
        },
    },
    _tool_schema("plan_video_knowledge_run", ["media_path", "workspace"], optional=["title", "max_frames", "build_initial_bundle", "root", "project_root"]),
    _tool_schema("check_video_run_artifacts", ["bundle_dir"]),
    _tool_schema("init_project", ["root", "question"]),
    _tool_schema("add_source", ["root", "title"], optional=["url", "path", "source_type", "quality", "notes"]),
    _tool_schema("add_video", ["root", "video_path", "topic"], optional=["transcript_path"]),
    _tool_schema("import_sources", ["root", "import_path"], optional=["default_quality"]),
    _tool_schema("build_research_plan", ["root"], optional=["question", "write", "add_claims"]),
    _tool_schema("read_research_plan", ["root"]),
    _tool_schema("analyze_research_gaps", ["root"], optional=["query", "max_queries_per_round"]),
    _tool_schema("research_loop", ["root"], optional=["query", "mode", "rounds", "max_results", "max_queries_per_round", "no_network", "fetch", "base_url", "timeout_seconds", "status_timeout_seconds"]),
    _tool_schema("list_research_loops", ["root"], optional=["limit"]),
    _tool_schema("read_research_loop", ["root"], optional=["id"]),
    _tool_schema("export_research_loop_review_pack", ["root"], optional=["id", "output_dir"]),
    _tool_schema("ai_research_status", [], optional=["base_url"]),
    _tool_schema("plan_ai_research_search", ["root"], optional=["query", "mode", "max_results", "deep", "no_network", "fetch", "import_results", "base_url"]),
    _tool_schema("run_ai_research_search", ["root"], optional=["query", "mode", "max_results", "deep", "no_network", "fetch", "import_results", "base_url", "timeout_seconds"]),
    _tool_schema("import_ai_research_result", ["root", "result"], optional=["import_sources", "import_claims", "import_evidence"]),
    _tool_schema("vane_perplexica_status", [], optional=["base_url"]),
    _tool_schema("plan_vane_perplexica_search", ["root"], optional=["query", "sources", "optimization_mode", "base_url", "chat_provider_id", "chat_model_key", "embedding_provider_id", "embedding_model_key", "system_instructions", "import_results"]),
    _tool_schema("run_vane_perplexica_search", ["root"], optional=["query", "sources", "optimization_mode", "base_url", "chat_provider_id", "chat_model_key", "embedding_provider_id", "embedding_model_key", "system_instructions", "import_results", "timeout_seconds"]),
    _tool_schema("import_vane_perplexica_result", ["root", "result"], optional=["import_sources"]),
    _tool_schema("plan_external_researcher_session", ["root"], optional=["question", "clarification_answers", "providers", "source_policy", "output_language"]),
    _tool_schema("answer_external_researcher_followup", ["root", "followup_question"], optional=["manual_answer", "original_question", "source_policy", "auto_after_seconds"]),
    _tool_schema("import_external_researcher_report", ["root", "provider", "report_text"], optional=["prompt_text", "report_url", "notes", "import_as_source"]),
    _tool_schema("list_external_researcher_reports", ["root"]),
    _tool_schema("export_external_researcher_bundle", ["root"], optional=["output_dir"]),
    _tool_schema("plan_external_researcher_automation", ["root"], optional=["question", "clarification_answers", "providers", "source_policy", "output_language", "profile_config_path", "followup_wait_seconds", "max_wait_seconds"]),
    _tool_schema("run_external_researcher_automation", ["root"], optional=["automation_plan", "question", "clarification_answers", "providers", "source_policy", "output_language", "profile_config_path", "followup_wait_seconds", "max_wait_seconds", "headless", "import_as_source", "dry_run"]),
    _tool_schema("check_external_researcher_automation_profiles", ["root"], optional=["automation_plan", "question", "clarification_answers", "providers", "source_policy", "output_language", "profile_config_path", "followup_wait_seconds", "max_wait_seconds", "live", "headless", "timeout_seconds"]),
    _tool_schema("prepare_external_researcher_login_profiles", ["root"], optional=["providers", "automation_plan", "profile_config_path", "keep_open_seconds", "timeout_seconds", "headless", "live"]),
    _tool_schema("write_external_researcher_profile_template", ["root"], optional=["output_path"]),
    _tool_schema("run_omnigent_external_research_poc", ["root"], optional=["question", "clarification_answers", "providers", "source_policy", "output_language", "profile_config_path", "followup_wait_seconds", "max_wait_seconds", "headless", "import_as_source", "dry_run"]),
    _tool_schema("plan_fetch_source_content", ["root"], optional=["source_id", "url", "title", "claim_id", "fetch_profile", "backend", "extractor", "use_browser", "include_raw", "timeout_seconds", "import_source", "create_candidate_evidence"]),
    _tool_schema("fetch_source_content", ["root"], optional=["source_id", "url", "title", "claim_id", "fetch_profile", "backend", "extractor", "use_browser", "include_raw", "timeout_seconds", "import_source", "create_candidate_evidence"]),
    _tool_schema("import_video_knowledge_artifacts", ["root", "bundle_dir"], optional=["title", "claim_id", "source_quality"]),
    _tool_schema("route_research_task", ["root"], optional=["question", "material_hint", "write"]),
    _tool_schema("audit_research_gates", ["root"], optional=["target_stage", "write"]),
    _tool_schema("run_multi_perspective_review", ["root"], optional=["write"]),
    _tool_schema("run_reader_persona_review", ["root"], optional=["write"]),
    _tool_schema("run_workflow_engine", ["root"], optional=["write"]),
    _tool_schema("review_source", ["root", "source_id", "quality"], optional=["reason", "reviewer"]),
    _tool_schema("add_claim", ["root", "text"], optional=["notes"]),
    _tool_schema("add_evidence", ["root", "claim_id", "source_id", "quote_or_note"], optional=["relation", "confidence", "notes"]),
    _tool_schema("run_guarded_e2e_fixture", ["root"], optional=["reviewer", "stop_after"]),
    _tool_schema("review_evidence", ["root", "evidence_id", "status"], optional=["relation", "confidence", "notes", "reviewer"]),
    _tool_schema("review_graph_edge", ["root", "from_id", "to_id", "status"], optional=["note"]),
    _tool_schema("generate_graph_candidates", ["root"]),
    _tool_schema("list_graph_candidates", ["root"], optional=["status", "edge_type"]),
    _tool_schema("review_graph_candidate", ["root", "from_id", "to_id", "status"], optional=["note", "reviewer"]),
    _tool_schema("export_reviewed_graph", ["root"], optional=["output_dir"]),
    _tool_schema("list_records", ["root", "kind"]),
    _tool_schema("draft_answer", ["root"], optional=["include_candidate"]),
    _tool_schema("export_final_answer", ["root"], optional=["output_dir", "allow_incomplete"]),
    _tool_schema("export_research_output", ["root"], optional=["output_path", "scope", "audience", "requested_outputs", "scope_constraints"]),
    _tool_schema("render_project_overview", ["root"]),
    _tool_schema("export_obsidian", ["root", "vault"], optional=["folder"]),
    _tool_schema("export_research_pack", ["root"], optional=["output_dir"]),
    _tool_schema("export_research_pack_to_obsidian", ["root", "vault"], optional=["folder"]),
    _tool_schema("create_logseq_review_handoff", ["root"], optional=["output_dir"]),
    _tool_schema("write_graph_csv", ["root"]),
    _tool_schema("get_project_status", ["root"]),
    _tool_schema("get_project_dashboard", ["root"]),
    _tool_schema("build_demo_project", ["root"]),
    _tool_schema("get_project_overview", ["root"]),
    _tool_schema("get_agent_manifest", [], optional=["root"]),
    _tool_schema("get_tool_health_dashboard", []),
    _tool_schema("get_tool_bridge_status", ["root"], optional=["limit"]),
    _tool_schema("list_bridge_runs", ["root"], optional=["tool", "status", "limit"]),
    _tool_schema("read_bridge_run", ["root", "id"]),
    _tool_schema("retry_bridge_run_plan", ["root", "id"]),
    _tool_schema("plan_bridge_action", ["root", "action"], optional=["args"]),
    _tool_schema("run_bridge_action", ["root", "action"], optional=["args", "execute", "timeout_seconds"]),
    _tool_schema("enqueue_bridge_actions", ["root"]),
    _tool_schema("audit_completeness", ["root"]),
    _tool_schema("audit_cockpit_readiness", [], optional=["root"]),
    _tool_schema("audit_sync_safety", [], optional=["repo"]),
    _tool_schema("get_gate_details", ["root"], optional=["gate_id"]),
    _tool_schema("get_review_queue", ["root"], optional=["item_type"]),
    _tool_schema("run_next_step", ["root", "gate_id"], optional=["write"]),
    _tool_schema("read_workflow_artifact", ["root", "artifact_id"], optional=["format"]),
    _tool_schema("build_agent_runbook", ["root"]),
    _tool_schema("enqueue_runbook_tasks", ["root"]),
    _tool_schema("list_work_queue", ["root"], optional=["status"]),
    _tool_schema("update_work_queue_item", ["root", "id", "status"], optional=["note"]),
    _tool_schema("run_work_queue_item", ["root", "id"], optional=["execute", "timeout_seconds"]),
    _tool_schema("run_local_tool_action", ["tool_id", "action"], optional=["args", "execute", "timeout_seconds"]),
    _tool_schema("add_source_inbox_item", ["root", "kind", "title"], optional=["location", "url", "path", "source_tool", "quality_hint", "notes"]),
    _tool_schema("list_source_inbox", ["root"], optional=["status"]),
    _tool_schema("import_source_inbox_item", ["root", "id"], optional=["source_quality"]),
    _tool_schema("reject_source_inbox_item", ["root", "id"], optional=["note"]),
]


def list_mcp_tools() -> list[dict[str, Any]]:
    return TOOL_DEFINITIONS


def call_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    mapping: dict[str, Callable[..., Any]] = {
        "run_video_knowledge_tool": _tool_run_video_knowledge_tool,
        "plan_video_knowledge_run": lambda **kwargs: plan_video_knowledge_run(
            kwargs["media_path"],
            kwargs["workspace"],
            title=kwargs.get("title", ""),
            max_frames=int(kwargs.get("max_frames", 80)),
            build_initial_bundle=bool(kwargs.get("build_initial_bundle", True)),
            root=kwargs.get("root"),
            project_root=kwargs.get("project_root"),
        ),
        "check_video_run_artifacts": lambda **kwargs: check_video_run_artifacts(kwargs["bundle_dir"]),
        "init_project": lambda **kwargs: init_project(kwargs["root"], kwargs["question"]),
        "add_source": lambda **kwargs: add_source(kwargs["root"], title=kwargs["title"], url=kwargs.get("url", ""), path=kwargs.get("path", ""), source_type=kwargs.get("source_type", "web"), quality=kwargs.get("quality", "unknown"), notes=kwargs.get("notes", "")),
        "add_video": lambda **kwargs: add_video(kwargs["root"], kwargs["video_path"], topic=kwargs["topic"], transcript_path=kwargs.get("transcript_path")),
        "import_sources": lambda **kwargs: import_sources(kwargs["root"], kwargs["import_path"], default_quality=kwargs.get("default_quality", "unknown")),
        "build_research_plan": lambda **kwargs: build_research_plan(kwargs["root"], question=kwargs.get("question"), write=bool(kwargs.get("write", True)), add_claims=bool(kwargs.get("add_claims", False))),
        "read_research_plan": lambda **kwargs: read_research_plan(kwargs["root"]),
        "analyze_research_gaps": lambda **kwargs: analyze_research_gaps(kwargs["root"], query=kwargs.get("query"), max_queries_per_round=int(kwargs.get("max_queries_per_round", 3))),
        "research_loop": lambda **kwargs: run_research_loop(
            kwargs["root"],
            query=kwargs.get("query"),
            mode=kwargs.get("mode", "academic"),
            rounds=int(kwargs.get("rounds", 3)),
            max_results=int(kwargs.get("max_results", 8)),
            max_queries_per_round=int(kwargs.get("max_queries_per_round", 3)),
            no_network=bool(kwargs.get("no_network", False)),
            fetch=bool(kwargs.get("fetch", True)),
            base_url=kwargs.get("base_url"),
            timeout_seconds=int(kwargs.get("timeout_seconds", 240)),
            status_timeout_seconds=int(kwargs.get("status_timeout_seconds", 5)),
        ),
        "list_research_loops": lambda **kwargs: list_research_loops(kwargs["root"], limit=int(kwargs.get("limit", 20))),
        "read_research_loop": lambda **kwargs: read_research_loop(kwargs["root"], kwargs.get("id", "")),
        "export_research_loop_review_pack": lambda **kwargs: export_research_loop_review_pack(kwargs["root"], loop_id=kwargs.get("id", ""), output_dir=kwargs.get("output_dir")),
        "ai_research_status": lambda **kwargs: ai_research_status(kwargs.get("base_url")),
        "plan_ai_research_search": lambda **kwargs: plan_ai_research_search(
            kwargs["root"],
            query=kwargs.get("query"),
            mode=kwargs.get("mode", "auto"),
            max_results=int(kwargs.get("max_results", 8)),
            deep=bool(kwargs.get("deep", False)),
            no_network=bool(kwargs.get("no_network", False)),
            fetch=bool(kwargs.get("fetch", True)),
            import_results=bool(kwargs.get("import_results", False)),
            base_url=kwargs.get("base_url"),
        ),
        "run_ai_research_search": lambda **kwargs: run_ai_research_search(
            kwargs["root"],
            query=kwargs.get("query"),
            mode=kwargs.get("mode", "auto"),
            max_results=int(kwargs.get("max_results", 8)),
            deep=bool(kwargs.get("deep", False)),
            no_network=bool(kwargs.get("no_network", False)),
            fetch=bool(kwargs.get("fetch", True)),
            import_results=bool(kwargs.get("import_results", False)),
            base_url=kwargs.get("base_url"),
            timeout_seconds=int(kwargs.get("timeout_seconds", 120)),
        ),
        "import_ai_research_result": lambda **kwargs: import_ai_research_result(
            kwargs["root"],
            kwargs["result"],
            import_sources=bool(kwargs.get("import_sources", True)),
            import_claims=bool(kwargs.get("import_claims", True)),
            import_evidence=bool(kwargs.get("import_evidence", True)),
        ),
        "vane_perplexica_status": lambda **kwargs: vane_perplexica_status(kwargs.get("base_url")),
        "plan_vane_perplexica_search": lambda **kwargs: plan_vane_perplexica_search(
            kwargs["root"],
            query=kwargs.get("query"),
            sources=kwargs.get("sources"),
            optimization_mode=kwargs.get("optimization_mode", "balanced"),
            base_url=kwargs.get("base_url"),
            chat_provider_id=kwargs.get("chat_provider_id", ""),
            chat_model_key=kwargs.get("chat_model_key", ""),
            embedding_provider_id=kwargs.get("embedding_provider_id", ""),
            embedding_model_key=kwargs.get("embedding_model_key", ""),
            system_instructions=kwargs.get("system_instructions", ""),
            import_results=bool(kwargs.get("import_results", False)),
        ),
        "run_vane_perplexica_search": lambda **kwargs: run_vane_perplexica_search(
            kwargs["root"],
            query=kwargs.get("query"),
            sources=kwargs.get("sources"),
            optimization_mode=kwargs.get("optimization_mode", "balanced"),
            base_url=kwargs.get("base_url"),
            chat_provider_id=kwargs.get("chat_provider_id", ""),
            chat_model_key=kwargs.get("chat_model_key", ""),
            embedding_provider_id=kwargs.get("embedding_provider_id", ""),
            embedding_model_key=kwargs.get("embedding_model_key", ""),
            system_instructions=kwargs.get("system_instructions", ""),
            import_results=bool(kwargs.get("import_results", False)),
            timeout_seconds=int(kwargs.get("timeout_seconds", 120)),
        ),
        "import_vane_perplexica_result": lambda **kwargs: import_vane_perplexica_result(
            kwargs["root"],
            kwargs["result"],
            import_sources=bool(kwargs.get("import_sources", True)),
        ),
        "plan_external_researcher_session": lambda **kwargs: plan_external_researcher_session(
            kwargs["root"],
            question=kwargs.get("question"),
            clarification_answers=kwargs.get("clarification_answers", ""),
            providers=kwargs.get("providers"),
            source_policy=kwargs.get("source_policy", ""),
            output_language=kwargs.get("output_language", "中文"),
        ),
        "answer_external_researcher_followup": lambda **kwargs: answer_external_researcher_followup(
            kwargs["root"],
            followup_question=kwargs["followup_question"],
            manual_answer=kwargs.get("manual_answer", ""),
            original_question=kwargs.get("original_question"),
            source_policy=kwargs.get("source_policy", ""),
            auto_after_seconds=int(kwargs.get("auto_after_seconds", 10)),
        ),
        "import_external_researcher_report": lambda **kwargs: import_external_researcher_report(
            kwargs["root"],
            provider=kwargs["provider"],
            report_text=kwargs["report_text"],
            prompt_text=kwargs.get("prompt_text", ""),
            report_url=kwargs.get("report_url", ""),
            notes=kwargs.get("notes", ""),
            import_as_source=bool(kwargs.get("import_as_source", True)),
        ),
        "list_external_researcher_reports": lambda **kwargs: list_external_researcher_reports(kwargs["root"]),
        "export_external_researcher_bundle": lambda **kwargs: export_external_researcher_bundle(kwargs["root"], output_dir=kwargs.get("output_dir")),
        "plan_external_researcher_automation": lambda **kwargs: plan_external_researcher_automation(
            kwargs["root"],
            question=kwargs.get("question"),
            clarification_answers=kwargs.get("clarification_answers", ""),
            providers=kwargs.get("providers"),
            source_policy=kwargs.get("source_policy", ""),
            output_language=kwargs.get("output_language", "中文"),
            profile_config_path=kwargs.get("profile_config_path", ""),
            followup_wait_seconds=int(kwargs.get("followup_wait_seconds", 10)),
            max_wait_seconds=int(kwargs.get("max_wait_seconds", 900)),
        ),
        "run_external_researcher_automation": lambda **kwargs: run_external_researcher_automation(
            kwargs["root"],
            automation_plan=kwargs.get("automation_plan", ""),
            question=kwargs.get("question"),
            clarification_answers=kwargs.get("clarification_answers", ""),
            providers=kwargs.get("providers"),
            source_policy=kwargs.get("source_policy", ""),
            output_language=kwargs.get("output_language", "中文"),
            profile_config_path=kwargs.get("profile_config_path", ""),
            followup_wait_seconds=int(kwargs.get("followup_wait_seconds", 10)),
            max_wait_seconds=int(kwargs.get("max_wait_seconds", 900)),
            headless=bool(kwargs.get("headless", False)),
            import_as_source=bool(kwargs.get("import_as_source", True)),
            dry_run=bool(kwargs.get("dry_run", False)),
        ),
        "check_external_researcher_automation_profiles": lambda **kwargs: check_external_researcher_automation_profiles(
            kwargs["root"],
            automation_plan=kwargs.get("automation_plan", ""),
            question=kwargs.get("question"),
            clarification_answers=kwargs.get("clarification_answers", ""),
            providers=kwargs.get("providers"),
            source_policy=kwargs.get("source_policy", ""),
            output_language=kwargs.get("output_language", "中文"),
            profile_config_path=kwargs.get("profile_config_path", ""),
            followup_wait_seconds=int(kwargs.get("followup_wait_seconds", 10)),
            max_wait_seconds=int(kwargs.get("max_wait_seconds", 900)),
            live=bool(kwargs.get("live", False)),
            headless=bool(kwargs.get("headless", False)),
            timeout_seconds=int(kwargs.get("timeout_seconds", 30)),
        ),
        "prepare_external_researcher_login_profiles": lambda **kwargs: prepare_external_researcher_login_profiles(
            kwargs["root"],
            providers=kwargs.get("providers"),
            automation_plan=kwargs.get("automation_plan", ""),
            profile_config_path=kwargs.get("profile_config_path", ""),
            keep_open_seconds=int(kwargs.get("keep_open_seconds", 600)),
            timeout_seconds=int(kwargs.get("timeout_seconds", 45)),
            headless=bool(kwargs.get("headless", False)),
            live=bool(kwargs.get("live", False)),
        ),
        "write_external_researcher_profile_template": lambda **kwargs: write_external_researcher_profile_template(
            kwargs["root"],
            output_path=kwargs.get("output_path"),
        ),
        "run_omnigent_external_research_poc": lambda **kwargs: run_omnigent_external_research_poc(
            kwargs["root"],
            question=kwargs.get("question"),
            clarification_answers=kwargs.get("clarification_answers", ""),
            providers=kwargs.get("providers"),
            source_policy=kwargs.get("source_policy", ""),
            output_language=kwargs.get("output_language", "中文"),
            profile_config_path=kwargs.get("profile_config_path", ""),
            followup_wait_seconds=int(kwargs.get("followup_wait_seconds", 10)),
            max_wait_seconds=int(kwargs.get("max_wait_seconds", 900)),
            headless=bool(kwargs.get("headless", False)),
            import_as_source=bool(kwargs.get("import_as_source", True)),
            dry_run=bool(kwargs.get("dry_run", True)),
        ),
        "plan_fetch_source_content": lambda **kwargs: plan_fetch_source_content(
            kwargs["root"],
            source_id=kwargs.get("source_id"),
            url=kwargs.get("url"),
            title=kwargs.get("title"),
            claim_id=kwargs.get("claim_id"),
            fetch_profile=kwargs.get("fetch_profile", "generic"),
            backend=kwargs.get("backend", "auto"),
            extractor=kwargs.get("extractor", "auto"),
            use_browser=bool(kwargs.get("use_browser", False)),
            include_raw=bool(kwargs.get("include_raw", False)),
            timeout_seconds=int(kwargs.get("timeout_seconds", 30)),
            import_source=bool(kwargs.get("import_source", True)),
            create_candidate_evidence=bool(kwargs.get("create_candidate_evidence", False)),
        ),
        "fetch_source_content": lambda **kwargs: fetch_source_content(
            kwargs["root"],
            source_id=kwargs.get("source_id"),
            url=kwargs.get("url"),
            title=kwargs.get("title"),
            claim_id=kwargs.get("claim_id"),
            fetch_profile=kwargs.get("fetch_profile", "generic"),
            backend=kwargs.get("backend", "auto"),
            extractor=kwargs.get("extractor", "auto"),
            use_browser=bool(kwargs.get("use_browser", False)),
            include_raw=bool(kwargs.get("include_raw", False)),
            timeout_seconds=int(kwargs.get("timeout_seconds", 30)),
            import_source=bool(kwargs.get("import_source", True)),
            create_candidate_evidence=bool(kwargs.get("create_candidate_evidence", False)),
        ),
        "import_video_knowledge_artifacts": lambda **kwargs: import_video_knowledge_artifacts(
            kwargs["root"],
            kwargs["bundle_dir"],
            title=kwargs.get("title", ""),
            claim_id=kwargs.get("claim_id", ""),
            source_quality=kwargs.get("source_quality", "unknown"),
        ),
        "route_research_task": lambda **kwargs: route_research_task(
            kwargs["root"],
            question=kwargs.get("question"),
            material_hint=kwargs.get("material_hint", ""),
            write=bool(kwargs.get("write", True)),
        ),
        "audit_research_gates": lambda **kwargs: audit_research_gates(
            kwargs["root"],
            target_stage=kwargs.get("target_stage", "answer_draft"),
            write=bool(kwargs.get("write", True)),
        ),
        "run_multi_perspective_review": lambda **kwargs: run_multi_perspective_review(
            kwargs["root"],
            write=bool(kwargs.get("write", True)),
        ),
        "run_reader_persona_review": lambda **kwargs: run_reader_persona_review(
            kwargs["root"],
            write=bool(kwargs.get("write", True)),
        ),
        "run_workflow_engine": lambda **kwargs: run_workflow_engine(kwargs["root"], write=bool(kwargs.get("write", True))),
        "review_source": lambda **kwargs: review_source(kwargs["root"], source_id=kwargs["source_id"], quality=kwargs["quality"], reason=kwargs.get("reason", ""), reviewer=kwargs.get("reviewer", "human")),
        "add_claim": lambda **kwargs: add_claim(kwargs["root"], text=kwargs["text"], notes=kwargs.get("notes", "")),
        "add_evidence": lambda **kwargs: add_evidence(kwargs["root"], claim_id=kwargs["claim_id"], source_id=kwargs["source_id"], quote_or_note=kwargs["quote_or_note"], relation=kwargs.get("relation", "unknown"), confidence=kwargs.get("confidence", "unknown"), notes=kwargs.get("notes", "")),
        "run_guarded_e2e_fixture": lambda **kwargs: run_guarded_e2e_fixture(kwargs["root"], reviewer=kwargs.get("reviewer", "guarded-e2e-fixture"), stop_after=kwargs.get("stop_after")),
        "review_evidence": lambda **kwargs: review_evidence(kwargs["root"], evidence_id=kwargs["evidence_id"], status=kwargs["status"], relation=kwargs.get("relation"), confidence=kwargs.get("confidence"), notes=kwargs.get("notes", ""), reviewer=kwargs.get("reviewer", "human")),
        "review_graph_edge": lambda **kwargs: review_graph_edge(kwargs["root"], from_id=kwargs["from_id"], to_id=kwargs["to_id"], status=kwargs["status"], note=kwargs.get("note", "")),
        "generate_graph_candidates": lambda **kwargs: generate_graph_candidates(kwargs["root"]),
        "list_graph_candidates": lambda **kwargs: list_graph_candidates(kwargs["root"], status=kwargs.get("status"), edge_type=kwargs.get("edge_type")),
        "review_graph_candidate": lambda **kwargs: review_graph_candidate(kwargs["root"], from_id=kwargs["from_id"], to_id=kwargs["to_id"], status=kwargs["status"], note=kwargs.get("note", ""), reviewer=kwargs.get("reviewer", "human")),
        "export_reviewed_graph": lambda **kwargs: export_reviewed_graph(kwargs["root"], output_dir=kwargs.get("output_dir")),
        "list_records": lambda **kwargs: list_records(kwargs["root"], kwargs["kind"]),
        "draft_answer": lambda **kwargs: draft_answer(kwargs["root"], include_candidate=bool(kwargs.get("include_candidate", False))),
        "export_final_answer": lambda **kwargs: export_final_answer(kwargs["root"], output_dir=kwargs.get("output_dir"), allow_incomplete=bool(kwargs.get("allow_incomplete", False))),
        "export_research_output": lambda **kwargs: export_research_output(
            kwargs["root"],
            output_path=kwargs.get("output_path"),
            scope=kwargs.get("scope", ""),
            audience=kwargs.get("audience", "general"),
            requested_outputs=kwargs.get("requested_outputs"),
            scope_constraints=kwargs.get("scope_constraints"),
        ),
        "render_project_overview": lambda **kwargs: render_project_overview(kwargs["root"]),
        "export_obsidian": lambda **kwargs: export_obsidian(kwargs["root"], kwargs["vault"], folder=kwargs.get("folder", "00_Inbox/AI/问题导向研究流程POC")),
        "export_research_pack": lambda **kwargs: export_research_pack(kwargs["root"], output_dir=kwargs.get("output_dir")),
        "export_research_pack_to_obsidian": lambda **kwargs: export_research_pack_to_obsidian(kwargs["root"], kwargs["vault"], folder=kwargs.get("folder", "AI Research/问题导向研究审核包")),
        "create_logseq_review_handoff": lambda **kwargs: create_logseq_review_handoff(kwargs["root"], output_dir=kwargs.get("output_dir")),
        "write_graph_csv": lambda **kwargs: {"path": str(write_graph_csv(kwargs["root"]))},
        "get_project_status": lambda **kwargs: get_project_status(kwargs["root"]),
        "get_project_dashboard": lambda **kwargs: get_project_dashboard(kwargs["root"]),
        "build_demo_project": lambda **kwargs: build_demo_project(kwargs["root"]),
        "get_project_overview": lambda **kwargs: get_project_overview(kwargs["root"]),
        "get_agent_manifest": lambda **kwargs: build_agent_manifest(kwargs.get("root")),
        "get_tool_health_dashboard": lambda **kwargs: get_tool_health_dashboard(),
        "get_tool_bridge_status": lambda **kwargs: build_tool_bridge_status(kwargs["root"], limit=int(kwargs.get("limit", 8))),
        "list_bridge_runs": lambda **kwargs: list_bridge_runs(kwargs["root"], tool=kwargs.get("tool"), status=kwargs.get("status"), limit=int(kwargs.get("limit", 20))),
        "read_bridge_run": lambda **kwargs: read_bridge_run(kwargs["root"], kwargs["id"]),
        "retry_bridge_run_plan": lambda **kwargs: retry_bridge_run_plan(kwargs["root"], kwargs["id"]),
        "plan_bridge_action": lambda **kwargs: plan_bridge_action(kwargs["root"], kwargs["action"], args=kwargs.get("args") if isinstance(kwargs.get("args"), dict) else {}),
        "run_bridge_action": lambda **kwargs: run_bridge_action(kwargs["root"], kwargs["action"], args=kwargs.get("args") if isinstance(kwargs.get("args"), dict) else {}, execute=bool(kwargs.get("execute", False)), timeout_seconds=int(kwargs.get("timeout_seconds", 120))),
        "enqueue_bridge_actions": lambda **kwargs: enqueue_bridge_actions(kwargs["root"]),
        "audit_completeness": lambda **kwargs: audit_research_completeness(kwargs["root"]),
        "audit_cockpit_readiness": lambda **kwargs: audit_cockpit_readiness(kwargs.get("root")),
        "audit_sync_safety": lambda **kwargs: audit_sync_safety(kwargs.get("repo") or "."),
        "get_gate_details": lambda **kwargs: get_gate_details(kwargs["root"], gate_id=kwargs.get("gate_id")),
        "get_review_queue": lambda **kwargs: get_review_queue(kwargs["root"], item_type=kwargs.get("item_type")),
        "run_next_step": lambda **kwargs: run_next_step(kwargs["root"], kwargs["gate_id"], write=bool(kwargs.get("write", True))),
        "read_workflow_artifact": lambda **kwargs: read_workflow_artifact(kwargs["root"], kwargs["artifact_id"], format=kwargs.get("format", "markdown")),
        "build_agent_runbook": lambda **kwargs: build_agent_runbook(kwargs["root"]),
        "enqueue_runbook_tasks": lambda **kwargs: enqueue_runbook_tasks(kwargs["root"]),
        "list_work_queue": lambda **kwargs: get_work_queue(kwargs["root"], status=kwargs.get("status")),
        "update_work_queue_item": lambda **kwargs: update_task_status(kwargs["root"], kwargs["id"], kwargs["status"], note=kwargs.get("note", "")),
        "run_work_queue_item": lambda **kwargs: run_work_queue_item(kwargs["root"], kwargs["id"], execute=bool(kwargs.get("execute", False)), timeout_seconds=int(kwargs.get("timeout_seconds", 60))),
        "run_local_tool_action": lambda **kwargs: run_local_tool_action(kwargs["tool_id"], kwargs["action"], args=kwargs.get("args") if isinstance(kwargs.get("args"), dict) else None, execute=bool(kwargs.get("execute", False)), timeout_seconds=int(kwargs.get("timeout_seconds", 60))),
        "add_source_inbox_item": lambda **kwargs: add_inbox_item(kwargs["root"], kind=kwargs["kind"], title=kwargs["title"], location=kwargs.get("location", ""), url=kwargs.get("url", ""), path=kwargs.get("path", ""), source_tool=kwargs.get("source_tool", ""), quality_hint=kwargs.get("quality_hint", "unknown"), notes=kwargs.get("notes", "")),
        "list_source_inbox": lambda **kwargs: get_source_inbox(kwargs["root"], status=kwargs.get("status")),
        "import_source_inbox_item": lambda **kwargs: import_inbox_item_as_source(kwargs["root"], kwargs["id"], source_quality=kwargs.get("source_quality", "unknown")),
        "reject_source_inbox_item": lambda **kwargs: reject_inbox_item(kwargs["root"], kwargs["id"], note=kwargs.get("note", "")),
    }
    if name not in mapping:
        raise ValueError(f"unknown tool: {name}")
    return _jsonable(mapping[name](**arguments))


def _tool_run_video_knowledge_tool(args: list[str], root: str | None = None, timeout_seconds: int = 0) -> dict[str, Any]:
    return run_video_knowledge_tool(args=args, root=root, timeout_seconds=timeout_seconds)


def build_fastmcp_server() -> Any:
    from fastmcp import FastMCP

    server = FastMCP("question-research-poc")

    @server.tool()
    def run_video_knowledge_tool_tool(args: list[str], root: str | None = None, timeout_seconds: int = 0) -> dict[str, Any]:
        return _tool_run_video_knowledge_tool(args=args, root=root, timeout_seconds=timeout_seconds)

    @server.tool()
    def plan_video_knowledge_run_tool(
        media_path: str,
        workspace: str,
        title: str = "",
        max_frames: int = 80,
        build_initial_bundle: bool = True,
        root: str | None = None,
    ) -> dict[str, Any]:
        return plan_video_knowledge_run(
            media_path,
            workspace,
            title=title,
            max_frames=max_frames,
            build_initial_bundle=build_initial_bundle,
            root=root,
        )

    @server.tool()
    def call_question_research_tool(tool: str, arguments: dict[str, Any]) -> Any:
        return call_mcp_tool(tool, arguments)

    @server.tool()
    def list_question_research_tools() -> list[dict[str, Any]]:
        return list_mcp_tools()

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="question-research-poc MCP server/tools")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--call")
    parser.add_argument("--arguments", default="{}")
    args = parser.parse_args(argv)
    if args.list_tools:
        print(json.dumps(list_mcp_tools(), ensure_ascii=False, indent=2))
        return 0
    if args.call:
        print(json.dumps(call_mcp_tool(args.call, json.loads(args.arguments)), ensure_ascii=False, indent=2))
        return 0
    server = build_fastmcp_server()
    server.run()
    return 0


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return value.__dict__
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return str(value) if hasattr(value, "__fspath__") else value


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
