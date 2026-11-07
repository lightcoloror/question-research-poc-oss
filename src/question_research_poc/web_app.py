from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .ai_research_bridge import ai_research_status, import_ai_research_result, plan_ai_research_search, run_ai_research_search
from .agent_interface import get_gate_details, get_review_queue
from .agent_manifest import build_agent_manifest
from .agent_runbook import build_agent_runbook
from .bridge_actions import enqueue_bridge_actions, plan_bridge_action, run_bridge_action
from .bridge_runs import list_bridge_runs, read_bridge_run, retry_bridge_run_plan
from .cockpit_readiness import audit_cockpit_readiness
from .completeness_audit import audit_research_completeness
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
    save_external_researcher_report_draft,
    write_external_researcher_profile_template,
)
from .final_answer import export_final_answer
from .graph_candidates import export_reviewed_graph, generate_graph_candidates, list_graph_candidates, review_graph_candidate
from .dashboard import build_project_dashboard
from .local_tool_health import build_local_tool_health_dashboard
from .orchestrator import (
    add_claim,
    add_evidence,
    add_source,
    add_video,
    draft_answer,
    init_project,
    list_records,
    render_project_overview,
    review_evidence,
    review_source,
)
from .project_overview import build_project_overview
from .research_gaps import analyze_research_gaps
from .research_loop import export_research_loop_review_pack, list_research_loops, read_research_loop, run_research_loop
from .research_plan import build_research_plan, read_research_plan
from .research_pack import create_logseq_review_handoff, export_research_pack, export_research_pack_to_obsidian
from .review_state import build_review_queue, build_workflow_payload
from .runtime_config import RUNTIME_CONFIG_PATH, default_project_root, load_runtime_config, web_host, web_port, web_url
from .runtime_paths import tool_registry_path
from .source_inbox import add_inbox_item, get_source_inbox, import_inbox_item_as_source, reject_inbox_item
from .sync_safety import audit_sync_safety
from .tool_bridge_status import build_tool_bridge_status
from .tool_executor import run_local_tool_action
from .storage import load_project
from .vane_perplexica_bridge import import_vane_perplexica_result, plan_vane_perplexica_search, run_vane_perplexica_search, vane_perplexica_status
from .video_artifact_import import import_video_knowledge_artifacts
from .video_knowledge_bridge import check_video_run_artifacts, plan_video_knowledge_run, run_video_knowledge_tool
from .web_fetch_bridge import fetch_source_content, plan_fetch_source_content
from .work_queue import enqueue_runbook_tasks, get_work_queue, run_work_queue_item, update_task_status
from .workflow_engine import (
    audit_research_gates,
    route_research_task,
    run_multi_perspective_review,
    run_reader_persona_review,
    run_workflow_engine,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "web"
DEFAULT_PROJECT_ROOT = default_project_root()


def run_web_ui(host: str | None = None, port: int | None = None, *, open_browser: bool = False) -> dict[str, Any]:
    config = load_runtime_config()
    actual_host = host or web_host(config)
    actual_port = int(port if port is not None else web_port(config))
    server = ThreadingHTTPServer((actual_host, actual_port), _handler_factory())
    url = f"http://{actual_host}:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        print(json.dumps({"ok": True, "url": url, "host": actual_host, "port": actual_port, "config": str(RUNTIME_CONFIG_PATH)}, ensure_ascii=False), flush=True)
        server.serve_forever()
    finally:
        server.server_close()
    return {"ok": True, "url": url}


def _handler_factory() -> type[BaseHTTPRequestHandler]:
    class ResearchControllerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    self._send_static("index.html")
                elif parsed.path in {"/index.html", "/styles.css", "/app.js"}:
                    self._send_static(parsed.path.lstrip("/"))
                elif parsed.path.startswith("/assets/"):
                    self._send_static(parsed.path.lstrip("/"))
                elif parsed.path == "/api/project":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(_project_payload(root))
                elif parsed.path == "/api/draft":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    include_candidate = _query_value(parsed.query, "include_candidate") == "1"
                    self._send_json({"markdown": draft_answer(root, include_candidate=include_candidate)})
                elif parsed.path == "/api/overview":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json({"markdown": render_project_overview(root)})
                elif parsed.path == "/api/project-overview":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(build_project_overview(root))
                elif parsed.path == "/api/agent/manifest":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(build_agent_manifest(root))
                elif parsed.path == "/api/tools":
                    self._send_json(_tools_payload())
                elif parsed.path == "/api/tool-health-dashboard":
                    self._send_json(build_local_tool_health_dashboard())
                elif parsed.path == "/api/tool-bridge-status":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    limit = int(_query_value(parsed.query, "limit") or 8)
                    self._send_json(build_tool_bridge_status(root, limit=limit))
                elif parsed.path == "/api/bridge-runs":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    limit = int(_query_value(parsed.query, "limit") or 20)
                    self._send_json(list_bridge_runs(root, tool=_query_value(parsed.query, "tool") or None, status=_query_value(parsed.query, "status") or None, limit=limit))
                elif parsed.path == "/api/bridge-run":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(read_bridge_run(root, _query_value(parsed.query, "id") or ""))
                elif parsed.path == "/api/completeness-audit":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(audit_research_completeness(root))
                elif parsed.path == "/api/cockpit-readiness":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(audit_cockpit_readiness(root))
                elif parsed.path == "/api/sync-safety":
                    repo = _query_value(parsed.query, "repo") or str(Path(__file__).resolve().parents[2])
                    self._send_json(audit_sync_safety(repo))
                elif parsed.path == "/api/research-plan":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json({"ok": True, "plan": read_research_plan(root)})
                elif parsed.path == "/api/research-loops":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    limit = int(_query_value(parsed.query, "limit") or 20)
                    self._send_json(list_research_loops(root, limit=limit))
                elif parsed.path == "/api/research-loop":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(read_research_loop(root, _query_value(parsed.query, "id") or ""))
                elif parsed.path == "/api/ai-research-status":
                    base_url = _query_value(parsed.query, "base_url") or None
                    self._send_json(ai_research_status(base_url))
                elif parsed.path == "/api/vane-perplexica-status":
                    base_url = _query_value(parsed.query, "base_url") or None
                    self._send_json(vane_perplexica_status(base_url))
                elif parsed.path == "/api/external-researcher-reports":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    self._send_json(list_external_researcher_reports(root))
                elif parsed.path == "/api/work-queue":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    status = _query_value(parsed.query, "status") or None
                    self._send_json(get_work_queue(root, status=status))
                elif parsed.path == "/api/source-inbox":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    status = _query_value(parsed.query, "status") or None
                    self._send_json(get_source_inbox(root, status=status))
                elif parsed.path == "/api/gate-details":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    gate_id = _query_value(parsed.query, "gate_id") or None
                    self._send_json({"ok": True, **get_gate_details(root, gate_id=gate_id)})
                elif parsed.path == "/api/review-queue":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    item_type = _query_value(parsed.query, "item_type") or None
                    self._send_json({"ok": True, **get_review_queue(root, item_type=item_type)})
                elif parsed.path == "/api/graph-candidates":
                    root = _query_value(parsed.query, "root") or str(DEFAULT_PROJECT_ROOT)
                    status = _query_value(parsed.query, "status") or None
                    edge_type = _query_value(parsed.query, "edge_type") or None
                    self._send_json(list_graph_candidates(root, status=status, edge_type=edge_type))
                else:
                    self._send_json({"ok": False, "error": "not found"}, status=404)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = self._read_body()
                root = body.get("root") or str(DEFAULT_PROJECT_ROOT)
                if parsed.path == "/api/project/init":
                    result = init_project(root, str(body.get("question") or ""))
                    self._send_json({"ok": True, "project": _jsonable(result), "state": _project_payload(root)})
                elif parsed.path == "/api/source":
                    result = add_source(
                        root,
                        title=str(body.get("title") or ""),
                        url=str(body.get("url") or ""),
                        path=str(body.get("path") or ""),
                        source_type=str(body.get("source_type") or "web"),
                        quality=str(body.get("quality") or "unknown"),
                        notes=str(body.get("notes") or ""),
                    )
                    self._send_json({"ok": True, "source": _jsonable(result), "state": _project_payload(root)})
                elif parsed.path == "/api/source-inbox/add":
                    result = add_inbox_item(
                        root,
                        kind=str(body.get("kind") or "web_page"),
                        title=str(body.get("title") or ""),
                        location=str(body.get("location") or ""),
                        url=str(body.get("url") or ""),
                        path=str(body.get("path") or ""),
                        source_tool=str(body.get("source_tool") or ""),
                        quality_hint=str(body.get("quality_hint") or "unknown"),
                        notes=str(body.get("notes") or ""),
                    )
                    self._send_json({"ok": True, "item": result, "source_inbox": get_source_inbox(root), "state": _project_payload(root)})
                elif parsed.path == "/api/source-inbox/import":
                    result = import_inbox_item_as_source(root, str(body.get("id") or ""), source_quality=str(body.get("source_quality") or "unknown"))
                    self._send_json({"ok": True, "result": result, "source_inbox": get_source_inbox(root), "state": _project_payload(root)})
                elif parsed.path == "/api/source-inbox/reject":
                    result = reject_inbox_item(root, str(body.get("id") or ""), note=str(body.get("note") or ""))
                    self._send_json({"ok": True, "item": result, "source_inbox": get_source_inbox(root), "state": _project_payload(root)})
                elif parsed.path == "/api/video":
                    result = add_video(root, str(body.get("video_path") or ""), topic=str(body.get("topic") or "视频资料"))
                    self._send_json({"ok": True, "video": result, "state": _project_payload(root)})
                elif parsed.path in {"/api/source/review", "/api/review-source"}:
                    result = review_source(
                        root,
                        source_id=str(body.get("source_id") or ""),
                        quality=str(body.get("quality") or "unknown"),
                        reason=str(body.get("reason") or ""),
                    )
                    self._send_json({"ok": True, "review": _jsonable(result), "state": _project_payload(root)})
                elif parsed.path == "/api/claim":
                    result = add_claim(root, text=str(body.get("text") or ""), notes=str(body.get("notes") or ""))
                    self._send_json({"ok": True, "claim": _jsonable(result), "state": _project_payload(root)})
                elif parsed.path == "/api/evidence":
                    result = add_evidence(
                        root,
                        claim_id=str(body.get("claim_id") or ""),
                        source_id=str(body.get("source_id") or ""),
                        quote_or_note=str(body.get("quote_or_note") or ""),
                        relation=str(body.get("relation") or "unknown"),
                        confidence=str(body.get("confidence") or "unknown"),
                        notes=str(body.get("notes") or ""),
                    )
                    self._send_json({"ok": True, "evidence": _jsonable(result), "state": _project_payload(root)})
                elif parsed.path in {"/api/evidence/review", "/api/review-evidence"}:
                    result = review_evidence(
                        root,
                        evidence_id=str(body.get("evidence_id") or ""),
                        status=str(body.get("status") or "candidate"),
                        relation=str(body.get("relation") or "") or None,
                        confidence=str(body.get("confidence") or "") or None,
                        notes=str(body.get("notes") or ""),
                    )
                    self._send_json({"ok": True, "review": result, "state": _project_payload(root)})
                elif parsed.path == "/api/video-knowledge":
                    args = body.get("args") if isinstance(body.get("args"), list) else []
                    result = run_video_knowledge_tool([str(item) for item in args], timeout_seconds=int(body.get("timeout_seconds") or 60))
                    self._send_json({"ok": result.get("ok", False), "result": result})
                elif parsed.path == "/api/video-knowledge-plan":
                    result = plan_video_knowledge_run(
                        str(body.get("media_path") or ""),
                        str(body.get("workspace") or ""),
                        title=str(body.get("title") or ""),
                        max_frames=int(body.get("max_frames") or 80),
                        build_initial_bundle=bool(body.get("build_initial_bundle", True)),
                        root=str(body.get("video_knowledge_root") or "") or None,
                        project_root=root,
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/check-video-run-artifacts":
                    result = check_video_run_artifacts(str(body.get("bundle_dir") or ""))
                    self._send_json({"ok": result.get("ok", False), "result": result})
                elif parsed.path == "/api/import-video-knowledge-artifacts":
                    result = import_video_knowledge_artifacts(
                        root,
                        str(body.get("bundle_dir") or ""),
                        title=str(body.get("title") or ""),
                        claim_id=str(body.get("claim_id") or ""),
                        source_quality=str(body.get("source_quality") or "unknown"),
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/export-research-pack":
                    result = export_research_pack(root, output_dir=str(body.get("output_dir") or "") or None)
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/export-final-answer":
                    result = export_final_answer(
                        root,
                        output_dir=str(body.get("output_dir") or "") or None,
                        allow_incomplete=bool(body.get("allow_incomplete", False)),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)}, status=200 if result.get("ok") else 409)
                elif parsed.path == "/api/export-research-pack-obsidian":
                    result = export_research_pack_to_obsidian(
                        root,
                        str(body.get("vault") or ""),
                        folder=str(body.get("folder") or "AI Research/问题导向研究审核包"),
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/create-logseq-review-handoff":
                    result = create_logseq_review_handoff(root, output_dir=str(body.get("output_dir") or "") or None)
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/agent-runbook":
                    result = build_agent_runbook(root)
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/enqueue-runbook-tasks":
                    result = enqueue_runbook_tasks(root)
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/update-work-queue-item":
                    result = update_task_status(
                        root,
                        str(body.get("id") or ""),
                        str(body.get("status") or "pending"),
                        note=str(body.get("note") or ""),
                    )
                    self._send_json({"ok": True, "result": result, "work_queue": get_work_queue(root), "state": _project_payload(root)})
                elif parsed.path == "/api/run-work-queue-item":
                    result = run_work_queue_item(
                        root,
                        str(body.get("id") or ""),
                        execute=bool(body.get("execute", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 60),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "work_queue": get_work_queue(root), "state": _project_payload(root)})
                elif parsed.path == "/api/research-plan":
                    result = build_research_plan(
                        root,
                        question=str(body.get("question") or "") or None,
                        write=bool(body.get("write", True)),
                        add_claims=bool(body.get("add_claims", False)),
                    )
                    self._send_json({"ok": True, "plan": result, "state": _project_payload(root)})
                elif parsed.path == "/api/analyze-research-gaps":
                    result = analyze_research_gaps(
                        root,
                        query=str(body.get("query") or "") or None,
                        max_queries_per_round=int(body.get("max_queries_per_round") or 3),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/research-loop":
                    result = run_research_loop(
                        root,
                        query=str(body.get("query") or "") or None,
                        mode=str(body.get("mode") or "academic"),
                        rounds=int(body.get("rounds") or 3),
                        max_results=int(body.get("max_results") or 8),
                        max_queries_per_round=int(body.get("max_queries_per_round") or 3),
                        no_network=bool(body.get("no_network", False)),
                        fetch=bool(body.get("fetch", True)),
                        base_url=str(body.get("base_url") or "") or None,
                        timeout_seconds=int(body.get("timeout_seconds") or 240),
                        status_timeout_seconds=int(body.get("status_timeout_seconds") or 5),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "loops": list_research_loops(root), "state": _project_payload(root)})
                elif parsed.path == "/api/export-research-loop-review-pack":
                    result = export_research_loop_review_pack(
                        root,
                        loop_id=str(body.get("id") or ""),
                        output_dir=str(body.get("output_dir") or "") or None,
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "loops": list_research_loops(root), "state": _project_payload(root)})
                elif parsed.path == "/api/ai-research-search":
                    result = run_ai_research_search(
                        root,
                        query=str(body.get("query") or "") or None,
                        mode=str(body.get("mode") or "auto"),
                        max_results=int(body.get("max_results") or 8),
                        deep=bool(body.get("deep", False)),
                        no_network=bool(body.get("no_network", False)),
                        fetch=bool(body.get("fetch", True)),
                        import_results=bool(body.get("import_results", False)),
                        base_url=str(body.get("base_url") or "") or None,
                        timeout_seconds=int(body.get("timeout_seconds") or 120),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/ai-research-plan":
                    result = plan_ai_research_search(
                        root,
                        query=str(body.get("query") or "") or None,
                        mode=str(body.get("mode") or "auto"),
                        max_results=int(body.get("max_results") or 8),
                        deep=bool(body.get("deep", False)),
                        no_network=bool(body.get("no_network", False)),
                        fetch=bool(body.get("fetch", True)),
                        import_results=bool(body.get("import_results", False)),
                        base_url=str(body.get("base_url") or "") or None,
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/import-ai-research-result":
                    result = import_ai_research_result(root, str(body.get("path") or ""))
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/vane-perplexica-search":
                    result = run_vane_perplexica_search(
                        root,
                        query=str(body.get("query") or "") or None,
                        sources=body.get("sources") or "web",
                        optimization_mode=str(body.get("optimization_mode") or "balanced"),
                        base_url=str(body.get("base_url") or "") or None,
                        chat_provider_id=str(body.get("chat_provider_id") or ""),
                        chat_model_key=str(body.get("chat_model_key") or ""),
                        embedding_provider_id=str(body.get("embedding_provider_id") or ""),
                        embedding_model_key=str(body.get("embedding_model_key") or ""),
                        system_instructions=str(body.get("system_instructions") or ""),
                        import_results=bool(body.get("import_results", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 120),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/vane-perplexica-plan":
                    result = plan_vane_perplexica_search(
                        root,
                        query=str(body.get("query") or "") or None,
                        sources=body.get("sources") or "web",
                        optimization_mode=str(body.get("optimization_mode") or "balanced"),
                        base_url=str(body.get("base_url") or "") or None,
                        chat_provider_id=str(body.get("chat_provider_id") or ""),
                        chat_model_key=str(body.get("chat_model_key") or ""),
                        embedding_provider_id=str(body.get("embedding_provider_id") or ""),
                        embedding_model_key=str(body.get("embedding_model_key") or ""),
                        system_instructions=str(body.get("system_instructions") or ""),
                        import_results=bool(body.get("import_results", False)),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/import-vane-perplexica-result":
                    result = import_vane_perplexica_result(root, str(body.get("path") or ""))
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-plan":
                    result = plan_external_researcher_session(
                        root,
                        question=str(body.get("question") or "") or None,
                        clarification_answers=str(body.get("clarification_answers") or ""),
                        providers=body.get("providers") or None,
                        source_policy=str(body.get("source_policy") or ""),
                        output_language=str(body.get("output_language") or "中文"),
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-followup":
                    result = answer_external_researcher_followup(
                        root,
                        followup_question=str(body.get("followup_question") or ""),
                        manual_answer=str(body.get("manual_answer") or ""),
                        original_question=str(body.get("original_question") or "") or None,
                        source_policy=str(body.get("source_policy") or ""),
                        auto_after_seconds=int(body.get("auto_after_seconds") or 10),
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-report":
                    result = import_external_researcher_report(
                        root,
                        provider=str(body.get("provider") or ""),
                        report_text=str(body.get("report_text") or ""),
                        prompt_text=str(body.get("prompt_text") or ""),
                        report_url=str(body.get("report_url") or ""),
                        notes=str(body.get("notes") or ""),
                        import_as_source=bool(body.get("import_as_source", True)),
                    )
                    self._send_json({"ok": True, "result": result, "reports": list_external_researcher_reports(root), "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-report-draft":
                    result = save_external_researcher_report_draft(
                        root,
                        provider=str(body.get("provider") or ""),
                        report_text=str(body.get("report_text") or ""),
                        prompt_text=str(body.get("prompt_text") or ""),
                        report_url=str(body.get("report_url") or ""),
                        notes=str(body.get("notes") or ""),
                    )
                    self._send_json({"ok": True, "result": result, "reports": list_external_researcher_reports(root), "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-export":
                    result = export_external_researcher_bundle(root, output_dir=str(body.get("output_dir") or "") or None)
                    self._send_json({"ok": True, "result": result, "reports": list_external_researcher_reports(root), "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-automation-plan":
                    result = plan_external_researcher_automation(
                        root,
                        question=str(body.get("question") or "") or None,
                        clarification_answers=str(body.get("clarification_answers") or ""),
                        providers=body.get("providers") or None,
                        source_policy=str(body.get("source_policy") or ""),
                        output_language=str(body.get("output_language") or "中文"),
                        profile_config_path=str(body.get("profile_config_path") or ""),
                        followup_wait_seconds=int(body.get("followup_wait_seconds") or 10),
                        max_wait_seconds=int(body.get("max_wait_seconds") or 900),
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-automation-run":
                    result = run_external_researcher_automation(
                        root,
                        automation_plan=str(body.get("automation_plan") or ""),
                        question=str(body.get("question") or "") or None,
                        clarification_answers=str(body.get("clarification_answers") or ""),
                        providers=body.get("providers") or None,
                        source_policy=str(body.get("source_policy") or ""),
                        output_language=str(body.get("output_language") or "中文"),
                        profile_config_path=str(body.get("profile_config_path") or ""),
                        followup_wait_seconds=int(body.get("followup_wait_seconds") or 10),
                        max_wait_seconds=int(body.get("max_wait_seconds") or 900),
                        headless=bool(body.get("headless", False)),
                        import_as_source=bool(body.get("import_as_source", True)),
                        dry_run=bool(body.get("dry_run", False)),
                    )
                    self._send_json({"ok": bool(result.get("ok", False)), "result": result, "reports": list_external_researcher_reports(root), "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-automation-check":
                    result = check_external_researcher_automation_profiles(
                        root,
                        automation_plan=str(body.get("automation_plan") or ""),
                        question=str(body.get("question") or "") or None,
                        clarification_answers=str(body.get("clarification_answers") or ""),
                        providers=body.get("providers") or None,
                        source_policy=str(body.get("source_policy") or ""),
                        output_language=str(body.get("output_language") or "中文"),
                        profile_config_path=str(body.get("profile_config_path") or ""),
                        followup_wait_seconds=int(body.get("followup_wait_seconds") or 10),
                        max_wait_seconds=int(body.get("max_wait_seconds") or 900),
                        live=bool(body.get("live", False)),
                        headless=bool(body.get("headless", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 30),
                    )
                    self._send_json({"ok": bool(result.get("ok", False)), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-login-profiles":
                    result = prepare_external_researcher_login_profiles(
                        root,
                        providers=body.get("providers") or None,
                        automation_plan=str(body.get("automation_plan") or ""),
                        profile_config_path=str(body.get("profile_config_path") or ""),
                        keep_open_seconds=int(body.get("keep_open_seconds") or 600),
                        timeout_seconds=int(body.get("timeout_seconds") or 45),
                        headless=bool(body.get("headless", False)),
                        live=bool(body.get("live", False)),
                    )
                    self._send_json({"ok": bool(result.get("ok", False)), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/external-researcher-profile-template":
                    result = write_external_researcher_profile_template(root, output_path=str(body.get("output_path") or "") or None)
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/fetch-source-content":
                    result = fetch_source_content(
                        root,
                        source_id=str(body.get("source_id") or "") or None,
                        url=str(body.get("url") or "") or None,
                        title=str(body.get("title") or "") or None,
                        claim_id=str(body.get("claim_id") or "") or None,
                        fetch_profile=str(body.get("fetch_profile") or "generic"),
                        backend=str(body.get("backend") or "auto"),
                        extractor=str(body.get("extractor") or "auto"),
                        use_browser=bool(body.get("use_browser", False)),
                        include_raw=bool(body.get("include_raw", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 30),
                        import_source=bool(body.get("import_source", True)),
                        create_candidate_evidence=bool(body.get("create_candidate_evidence", False)),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/fetch-source-plan":
                    result = plan_fetch_source_content(
                        root,
                        source_id=str(body.get("source_id") or "") or None,
                        url=str(body.get("url") or "") or None,
                        title=str(body.get("title") or "") or None,
                        claim_id=str(body.get("claim_id") or "") or None,
                        fetch_profile=str(body.get("fetch_profile") or "generic"),
                        backend=str(body.get("backend") or "auto"),
                        extractor=str(body.get("extractor") or "auto"),
                        use_browser=bool(body.get("use_browser", False)),
                        include_raw=bool(body.get("include_raw", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 30),
                        import_source=bool(body.get("import_source", True)),
                        create_candidate_evidence=bool(body.get("create_candidate_evidence", False)),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/route-research-task":
                    result = route_research_task(
                        root,
                        question=str(body.get("question") or "") or None,
                        material_hint=str(body.get("material_hint") or ""),
                        write=bool(body.get("write", True)),
                    )
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/audit-gates":
                    result = audit_research_gates(root, target_stage=str(body.get("target_stage") or "answer_draft"), write=bool(body.get("write", True)))
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/multi-perspective-review":
                    result = run_multi_perspective_review(root, write=bool(body.get("write", True)))
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/reader-persona-review":
                    result = run_reader_persona_review(root, write=bool(body.get("write", True)))
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/run-workflow-engine":
                    result = run_workflow_engine(root, write=bool(body.get("write", True)))
                    self._send_json({"ok": True, "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/tool-health":
                    tool = str(body.get("tool") or "")
                    self._send_json(_tool_health(tool))
                elif parsed.path == "/api/local-tool-action":
                    args = body.get("args") if isinstance(body.get("args"), dict) else None
                    result = run_local_tool_action(
                        str(body.get("tool_id") or ""),
                        str(body.get("action") or ""),
                        args=args,
                        execute=bool(body.get("execute", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 60),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result})
                elif parsed.path == "/api/plan-bridge-action":
                    result = plan_bridge_action(
                        root,
                        str(body.get("action") or ""),
                        args=body.get("args") if isinstance(body.get("args"), dict) else {},
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/run-bridge-action":
                    result = run_bridge_action(
                        root,
                        str(body.get("action") or ""),
                        args=body.get("args") if isinstance(body.get("args"), dict) else {},
                        execute=bool(body.get("execute", False)),
                        timeout_seconds=int(body.get("timeout_seconds") or 120),
                    )
                    self._send_json({"ok": result.get("ok", False), "result": result, "state": _project_payload(root)})
                elif parsed.path == "/api/enqueue-bridge-actions":
                    result = enqueue_bridge_actions(root)
                    self._send_json({"ok": True, "result": result, "work_queue": get_work_queue(root), "state": _project_payload(root)})
                elif parsed.path == "/api/retry-bridge-run-plan":
                    result = retry_bridge_run_plan(root, str(body.get("id") or ""))
                    self._send_json({"ok": True, "result": result})
                elif parsed.path == "/api/generate-graph-candidates":
                    result = generate_graph_candidates(root)
                    self._send_json({"ok": True, "result": result, "graph": list_graph_candidates(root), "state": _project_payload(root)})
                elif parsed.path == "/api/review-graph-candidate":
                    result = review_graph_candidate(
                        root,
                        from_id=str(body.get("from_id") or ""),
                        to_id=str(body.get("to_id") or ""),
                        status=str(body.get("status") or "candidate"),
                        note=str(body.get("note") or ""),
                    )
                    self._send_json({"ok": True, "result": result, "graph": list_graph_candidates(root), "state": _project_payload(root)})
                elif parsed.path == "/api/export-reviewed-graph":
                    result = export_reviewed_graph(root, output_dir=str(body.get("output_dir") or "") or None)
                    self._send_json({"ok": True, "result": result, "graph": list_graph_candidates(root), "state": _project_payload(root)})
                else:
                    self._send_json({"ok": False, "error": "not found"}, status=404)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_body(self) -> dict[str, Any]:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            if not raw.strip():
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _send_json(self, payload: object, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, html: str) -> None:
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_static(self, relative_path: str) -> None:
            path = (STATIC_ROOT / relative_path).resolve()
            if not str(path).startswith(str(STATIC_ROOT.resolve())) or not path.exists():
                self._send_json({"ok": False, "error": "static file not found"}, status=404)
                return
            data = path.read_bytes()
            if path.suffix == ".html":
                content_type = "text/html; charset=utf-8"
            elif path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif path.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif path.suffix == ".svg":
                content_type = "image/svg+xml"
            elif path.suffix == ".png":
                content_type = "image/png"
            elif path.suffix == ".ico":
                content_type = "image/x-icon"
            elif path.suffix in {".jpg", ".jpeg"}:
                content_type = "image/jpeg"
            elif path.suffix == ".webp":
                content_type = "image/webp"
            else:
                content_type = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return ResearchControllerHandler


def _project_payload(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).expanduser()
    workflow = build_workflow_payload(project_root)
    review_queue = build_review_queue(project_root)
    dashboard = build_project_dashboard(project_root, workflow=workflow, review_queue=review_queue)
    if not (project_root / "research.json").exists():
        return {
            "ok": False,
            "root": str(project_root),
            "project": None,
            "sources": [],
            "claims": [],
            "evidence": [],
            "graph": [],
            "reviews": [],
            "workflow": workflow,
            "review_queue": review_queue,
            "dashboard": dashboard,
            "overview": build_project_overview(project_root),
            "message": "project not initialized",
        }
    return {
        "ok": True,
        "root": str(project_root),
        "project": _jsonable(load_project(project_root)),
        "sources": list_records(project_root, "sources"),
        "claims": list_records(project_root, "claims"),
        "evidence": list_records(project_root, "evidence"),
        "graph": list_records(project_root, "graph"),
        "reviews": list_records(project_root, "reviews"),
        "workflow": workflow,
        "review_queue": review_queue,
        "dashboard": dashboard,
        "overview": build_project_overview(project_root),
    }

def _tools_payload() -> dict[str, Any]:
    registry_path = tool_registry_path()
    registry = _read_registry(registry_path)
    tools = registry.get("tools", {}) if isinstance(registry, dict) else {}
    preferred = [
        "question-research-poc",
        "ai-research-workflow",
        "web-content-fetcher",
        "video-knowledge-pipeline",
        "video-download-orchestrator",
        "bookwiki",
        "schedule-planner",
    ]
    rows = []
    for name in preferred:
        if name in tools and isinstance(tools[name], dict):
            item = dict(tools[name])
            item["name"] = name
            rows.append(item)
    config = load_runtime_config()
    return {"ok": True, "registry": str(registry_path), "runtime_config": str(RUNTIME_CONFIG_PATH), "web_url": web_url(config), "tools": rows, "health": build_local_tool_health_dashboard(registry_path)}


def _tool_health(tool: str) -> dict[str, Any]:
    registry = _read_registry(tool_registry_path())
    info = (registry.get("tools", {}) if isinstance(registry, dict) else {}).get(tool)
    if not isinstance(info, dict):
        return {"ok": False, "error": f"unknown tool: {tool}"}
    health = info.get("health_check") if isinstance(info.get("health_check"), dict) else {}
    command = str(health.get("command") or "")
    cwd = str(health.get("working_directory") or info.get("path") or os.getcwd())
    if not command:
        return {"ok": False, "tool": tool, "error": "tool has no health command"}
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "tool": tool,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": command,
    }


def _read_registry(registry_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(registry_path) if registry_path is not None else tool_registry_path()
    if not path.exists():
        return {"tools": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"tools": {}}


def _query_value(query: str, key: str) -> str:
    values = parse_qs(query).get(key) or [""]
    return values[0]


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return value.__dict__
    if isinstance(value, Path):
        return str(value)
    return value


