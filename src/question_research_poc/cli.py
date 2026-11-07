from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai_research_bridge import ai_research_status, import_ai_research_result, plan_ai_research_search, run_ai_research_agent_research, run_ai_research_search
from .agent_interface import get_gate_details, get_project_dashboard, get_project_overview, get_project_status, get_review_queue, get_tool_health_dashboard, read_workflow_artifact, run_next_step
from .agent_manifest import build_agent_manifest
from .agent_runbook import build_agent_runbook
from .bridge_actions import enqueue_bridge_actions, plan_bridge_action, run_bridge_action
from .bridge_runs import list_bridge_runs, read_bridge_run, retry_bridge_run_plan
from .bounded_deep_loop import BoundedDeepLoopError, run_bounded_deep_loop
from .offline_evidence_brief import run_offline_evidence_brief
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
from .final_answer import export_final_answer
from .graph_candidates import export_reviewed_graph, generate_graph_candidates, list_graph_candidates, review_graph_candidate
from .guarded_e2e_fixture import run_guarded_e2e_fixture
from .gateway_capability_closure import run_gateway_capability_closure
from .model_gateway_bridge import (
    run_gateway_embedding_candidate,
    run_gateway_model_assist,
)
from .omnigent_poc import run_omnigent_external_research_poc
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
from .runtime_config import RUNTIME_CONFIG_PATH, default_project_root, load_runtime_config, web_host, web_port, web_url
from .source_inbox import add_inbox_item, get_source_inbox, import_inbox_item_as_source, reject_inbox_item
from .sync_safety import audit_sync_safety
from .tool_bridge_status import build_tool_bridge_status
from .tool_executor import run_local_tool_action
from .vane_perplexica_bridge import import_vane_perplexica_result, plan_vane_perplexica_search, run_vane_perplexica_search, vane_perplexica_status
from .video_artifact_import import import_video_knowledge_artifacts
from .video_knowledge_bridge import check_video_run_artifacts, plan_video_knowledge_run, run_video_knowledge_tool
from .web_fetch_bridge import fetch_source_content, plan_fetch_source_content
from .web_app import run_web_ui
from .work_queue import enqueue_runbook_tasks, get_work_queue, run_work_queue_item, update_task_status
from .workflow_engine import audit_research_gates, route_research_task, run_multi_perspective_review, run_reader_persona_review, run_workflow_engine


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        if isinstance(exc, BoundedDeepLoopError):
            payload["error_code"] = exc.code
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if isinstance(result, str):
        print(result, end="" if result.endswith("\n") else "\n")
    else:
        print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Question-led research orchestration POC")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a research project")
    init.add_argument("research_question")
    init.add_argument("--project", required=True)

    source = sub.add_parser("add-source", help="Add a source")
    source.add_argument("--project", required=True)
    source.add_argument("--title", required=True)
    source.add_argument("--url")
    source.add_argument("--path")
    source.add_argument("--source-type", default="web")
    source.add_argument("--quality", default="unknown")
    source.add_argument("--notes", default="")

    import_cmd = sub.add_parser("import-sources", help="Import sources from JSON/JSONL")
    import_cmd.add_argument("path")
    import_cmd.add_argument("--project", required=True)
    import_cmd.add_argument("--default-quality", default="unknown")

    plan = sub.add_parser("plan-research", help="Build a question-led research plan")
    plan.add_argument("--project", required=True)
    plan.add_argument("--question")
    plan.add_argument("--no-write", action="store_true")
    plan.add_argument("--add-claims", action="store_true")

    read_plan = sub.add_parser("read-research-plan", help="Read the saved research plan")
    read_plan.add_argument("--project", required=True)

    gap_analysis = sub.add_parser("analyze-research-gaps", help="Analyze project research gaps without running live search")
    gap_analysis.add_argument("--project", required=True)
    gap_analysis.add_argument("--query")
    gap_analysis.add_argument("--max-queries-per-round", type=int, default=3)

    research_loop = sub.add_parser("research-loop", help="Run automatic gap-driven multi-round research through ai-research-workflow")
    research_loop.add_argument("--project", required=True)
    research_loop.add_argument("--query")
    research_loop.add_argument("--mode", default="academic")
    research_loop.add_argument("--rounds", type=int, default=3)
    research_loop.add_argument("--max-results", type=int, default=8)
    research_loop.add_argument("--max-queries-per-round", type=int, default=3)
    research_loop.add_argument("--no-network", action="store_true")
    research_loop.add_argument("--no-fetch", action="store_true")
    research_loop.add_argument("--base-url")
    research_loop.add_argument("--timeout-seconds", type=int, default=240)
    research_loop.add_argument("--status-timeout-seconds", type=int, default=5)

    list_loops = sub.add_parser("list-research-loops", help="List recorded gap-driven research loop runs")
    list_loops.add_argument("--project", required=True)
    list_loops.add_argument("--limit", type=int, default=20)

    read_loop = sub.add_parser("read-research-loop", help="Read a recorded research loop by id/path, or the latest one")
    read_loop.add_argument("--project", required=True)
    read_loop.add_argument("--id", default="")

    export_loop_pack = sub.add_parser("export-research-loop-review-pack", help="Export a human-readable research loop review pack")
    export_loop_pack.add_argument("--project", required=True)
    export_loop_pack.add_argument("--id", default="")
    export_loop_pack.add_argument("--output-dir")

    ai_status = sub.add_parser("ai-research-status", help="Check ai-research-workflow HTTP status")
    ai_status.add_argument("--base-url")

    deep_research = sub.add_parser(
        "deep-research",
        help="Codex-safe deep research entrypoint: preflight ai-research-workflow, run /v1/agent/research, and import candidates",
    )
    deep_research.add_argument("--project", required=True)
    deep_research.add_argument("--query")
    deep_research.add_argument("--mode", default="academic")
    deep_research.add_argument("--max-results", type=int, default=8)
    deep_research.add_argument("--no-network", action="store_true")
    deep_research.add_argument("--no-fetch", action="store_true")
    deep_research.add_argument("--base-url")
    deep_research.add_argument("--timeout-seconds", type=int, default=240)
    deep_research.add_argument("--status-timeout-seconds", type=int, default=5)

    ai_search = sub.add_parser("research-search", help="Dispatch a search to ai-research-workflow")
    ai_search.add_argument("--project", required=True)
    ai_search.add_argument("--query")
    ai_search.add_argument("--mode", default="auto")
    ai_search.add_argument("--max-results", type=int, default=8)
    ai_search.add_argument("--deep", action="store_true")
    ai_search.add_argument("--no-network", action="store_true")
    ai_search.add_argument("--no-fetch", action="store_true")
    ai_search.add_argument("--import-results", action="store_true")
    ai_search.add_argument("--base-url")
    ai_search.add_argument("--timeout-seconds", type=int, default=120)

    ai_plan = sub.add_parser("plan-ai-research-search", help="Plan a search dispatch to ai-research-workflow without calling the service")
    ai_plan.add_argument("--project", required=True)
    ai_plan.add_argument("--query")
    ai_plan.add_argument("--mode", default="auto")
    ai_plan.add_argument("--max-results", type=int, default=8)
    ai_plan.add_argument("--deep", action="store_true")
    ai_plan.add_argument("--no-network", action="store_true")
    ai_plan.add_argument("--no-fetch", action="store_true")
    ai_plan.add_argument("--import-results", action="store_true")
    ai_plan.add_argument("--base-url")

    import_ai = sub.add_parser("import-ai-research-result", help="Import ai-research-workflow result JSON into sources/claims/evidence")
    import_ai.add_argument("path")
    import_ai.add_argument("--project", required=True)
    import_ai.add_argument("--no-sources", action="store_true")
    import_ai.add_argument("--no-claims", action="store_true")
    import_ai.add_argument("--no-evidence", action="store_true")

    vane_status = sub.add_parser("vane-perplexica-status", help="Check Vane/Perplexica /api/providers status")
    vane_status.add_argument("--base-url")

    vane_search = sub.add_parser("vane-perplexica-search", help="Dispatch candidate-source search to Vane/Perplexica")
    vane_search.add_argument("--project", required=True)
    vane_search.add_argument("--query")
    vane_search.add_argument("--sources", default="web")
    vane_search.add_argument("--optimization-mode", default="balanced", choices=["speed", "balanced", "quality"])
    vane_search.add_argument("--base-url")
    vane_search.add_argument("--chat-provider-id", default="")
    vane_search.add_argument("--chat-model-key", default="")
    vane_search.add_argument("--embedding-provider-id", default="")
    vane_search.add_argument("--embedding-model-key", default="")
    vane_search.add_argument("--system-instructions", default="")
    vane_search.add_argument("--import-results", action="store_true")
    vane_search.add_argument("--timeout-seconds", type=int, default=120)

    vane_plan = sub.add_parser("plan-vane-perplexica-search", help="Plan Vane/Perplexica candidate-source search without calling /api/search")
    vane_plan.add_argument("--project", required=True)
    vane_plan.add_argument("--query")
    vane_plan.add_argument("--sources", default="web")
    vane_plan.add_argument("--optimization-mode", default="balanced", choices=["speed", "balanced", "quality"])
    vane_plan.add_argument("--base-url")
    vane_plan.add_argument("--chat-provider-id", default="")
    vane_plan.add_argument("--chat-model-key", default="")
    vane_plan.add_argument("--embedding-provider-id", default="")
    vane_plan.add_argument("--embedding-model-key", default="")
    vane_plan.add_argument("--system-instructions", default="")
    vane_plan.add_argument("--import-results", action="store_true")

    import_vane = sub.add_parser("import-vane-perplexica-result", help="Import Vane/Perplexica result JSON as candidate sources only")
    import_vane.add_argument("path")
    import_vane.add_argument("--project", required=True)
    import_vane.add_argument("--no-sources", action="store_true")

    external_plan = sub.add_parser("plan-external-researcher", help="Create a manual web deep-research prompt and handoff")
    external_plan.add_argument("--project", required=True)
    external_plan.add_argument("--question")
    external_plan.add_argument("--clarification-answers", default="")
    external_plan.add_argument("--providers", default="")
    external_plan.add_argument("--source-policy", default="")
    external_plan.add_argument("--output-language", default="中文")

    external_followup = sub.add_parser("answer-external-followup", help="Answer a provider follow-up question, manually or with the default fallback")
    external_followup.add_argument("--project", required=True)
    external_followup.add_argument("--followup-question", required=True)
    external_followup.add_argument("--manual-answer", default="")
    external_followup.add_argument("--original-question")
    external_followup.add_argument("--source-policy", default="")
    external_followup.add_argument("--auto-after-seconds", type=int, default=10)

    external_report = sub.add_parser("import-external-researcher-report", help="Save a pasted web deep-research report as candidate context")
    external_report.add_argument("--project", required=True)
    external_report.add_argument("--provider", required=True)
    external_report.add_argument("--report-text", required=True)
    external_report.add_argument("--prompt-text", default="")
    external_report.add_argument("--report-url", default="")
    external_report.add_argument("--notes", default="")
    external_report.add_argument("--no-source", action="store_true")

    external_list = sub.add_parser("list-external-researcher-reports", help="List saved external researcher reports")
    external_list.add_argument("--project", required=True)

    external_export = sub.add_parser("export-external-researcher-bundle", help="Export all external researcher reports into one Markdown bundle")
    external_export.add_argument("--project", required=True)
    external_export.add_argument("--output-dir")

    external_auto_plan = sub.add_parser("plan-external-researcher-automation", help="Create a browser automation plan for web deep-research providers")
    external_auto_plan.add_argument("--project", required=True)
    external_auto_plan.add_argument("--question")
    external_auto_plan.add_argument("--clarification-answers", default="")
    external_auto_plan.add_argument("--providers", default="")
    external_auto_plan.add_argument("--source-policy", default="")
    external_auto_plan.add_argument("--output-language", default="中文")
    external_auto_plan.add_argument("--profile-config-path", default="")
    external_auto_plan.add_argument("--followup-wait-seconds", type=int, default=10)
    external_auto_plan.add_argument("--max-wait-seconds", type=int, default=900)

    external_auto_run = sub.add_parser("run-external-researcher-automation", help="Run Playwright browser automation for web deep-research providers")
    external_auto_run.add_argument("--project", required=True)
    external_auto_run.add_argument("--automation-plan", default="")
    external_auto_run.add_argument("--question")
    external_auto_run.add_argument("--clarification-answers", default="")
    external_auto_run.add_argument("--providers", default="")
    external_auto_run.add_argument("--source-policy", default="")
    external_auto_run.add_argument("--output-language", default="中文")
    external_auto_run.add_argument("--profile-config-path", default="")
    external_auto_run.add_argument("--followup-wait-seconds", type=int, default=10)
    external_auto_run.add_argument("--max-wait-seconds", type=int, default=900)
    external_auto_run.add_argument("--headless", action="store_true")
    external_auto_run.add_argument("--no-source", action="store_true")
    external_auto_run.add_argument("--dry-run", action="store_true")

    external_auto_check = sub.add_parser("check-external-researcher-automation", help="Preflight provider profiles; --live opens pages but does not submit research")
    external_auto_check.add_argument("--project", required=True)
    external_auto_check.add_argument("--automation-plan", default="")
    external_auto_check.add_argument("--question")
    external_auto_check.add_argument("--clarification-answers", default="")
    external_auto_check.add_argument("--providers", default="")
    external_auto_check.add_argument("--source-policy", default="")
    external_auto_check.add_argument("--output-language", default="中文")
    external_auto_check.add_argument("--profile-config-path", default="")
    external_auto_check.add_argument("--followup-wait-seconds", type=int, default=10)
    external_auto_check.add_argument("--max-wait-seconds", type=int, default=900)
    external_auto_check.add_argument("--timeout-seconds", type=int, default=30)
    external_auto_check.add_argument("--headless", action="store_true")
    external_auto_check.add_argument("--live", action="store_true")

    omnigent_poc = sub.add_parser("run-omnigent-external-research-poc", help="Run the Omnigent-style external researcher orchestration PoC")
    omnigent_poc.add_argument("--project", required=True)
    omnigent_poc.add_argument("--question")
    omnigent_poc.add_argument("--clarification-answers", default="")
    omnigent_poc.add_argument("--providers", default="")
    omnigent_poc.add_argument("--source-policy", default="")
    omnigent_poc.add_argument("--output-language", default="中文")
    omnigent_poc.add_argument("--profile-config-path", default="")
    omnigent_poc.add_argument("--followup-wait-seconds", type=int, default=10)
    omnigent_poc.add_argument("--max-wait-seconds", type=int, default=900)
    omnigent_poc.add_argument("--headless", action="store_true")
    omnigent_poc.add_argument("--no-source", action="store_true")
    omnigent_poc.add_argument("--live", action="store_true")

    external_login_prep = sub.add_parser("prepare-external-researcher-login-profiles", help="Open or plan provider login/profile setup windows; --live opens browsers and submits nothing")
    external_login_prep.add_argument("--project", required=True)
    external_login_prep.add_argument("--providers", default="")
    external_login_prep.add_argument("--automation-plan", default="")
    external_login_prep.add_argument("--profile-config-path", default="")
    external_login_prep.add_argument("--keep-open-seconds", type=int, default=600)
    external_login_prep.add_argument("--timeout-seconds", type=int, default=45)
    external_login_prep.add_argument("--headless", action="store_true")
    external_login_prep.add_argument("--live", action="store_true")

    external_profile_template = sub.add_parser("write-external-researcher-profile-template", help="Write editable provider selector config for browser automation")
    external_profile_template.add_argument("--project", required=True)
    external_profile_template.add_argument("--output-path")

    fetch_source = sub.add_parser("fetch-source-content", help="Fetch a web source through web-content-fetcher and save readable artifacts")
    fetch_source.add_argument("--project", required=True)
    fetch_source.add_argument("--source-id")
    fetch_source.add_argument("--url")
    fetch_source.add_argument("--title")
    fetch_source.add_argument("--claim-id")
    fetch_source.add_argument("--fetch-profile", default="generic")
    fetch_source.add_argument("--backend", default="auto")
    fetch_source.add_argument("--extractor", default="auto")
    fetch_source.add_argument("--browser", action="store_true")
    fetch_source.add_argument("--include-raw", action="store_true")
    fetch_source.add_argument("--timeout-seconds", type=int, default=30)
    fetch_source.add_argument("--no-import-source", action="store_true")
    fetch_source.add_argument("--create-candidate-evidence", action="store_true")

    fetch_plan = sub.add_parser("plan-fetch-source-content", help="Plan a web-content-fetcher dispatch without fetching")
    fetch_plan.add_argument("--project", required=True)
    fetch_plan.add_argument("--source-id")
    fetch_plan.add_argument("--url")
    fetch_plan.add_argument("--title")
    fetch_plan.add_argument("--claim-id")
    fetch_plan.add_argument("--fetch-profile", default="generic")
    fetch_plan.add_argument("--backend", default="auto")
    fetch_plan.add_argument("--extractor", default="auto")
    fetch_plan.add_argument("--browser", action="store_true")
    fetch_plan.add_argument("--include-raw", action="store_true")
    fetch_plan.add_argument("--timeout-seconds", type=int, default=30)
    fetch_plan.add_argument("--no-import-source", action="store_true")
    fetch_plan.add_argument("--create-candidate-evidence", action="store_true")

    route_task = sub.add_parser("route-research-task", help="Route the task before running tools")
    route_task.add_argument("--project", required=True)
    route_task.add_argument("--question")
    route_task.add_argument("--material-hint", default="")
    route_task.add_argument("--no-write", action="store_true")

    gate_audit = sub.add_parser("audit-gates", help="Audit hard gates before moving to the next research stage")
    gate_audit.add_argument("--project", required=True)
    gate_audit.add_argument("--target-stage", default="answer_draft")
    gate_audit.add_argument("--no-write", action="store_true")

    perspective = sub.add_parser("multi-perspective-review", help="Create multi-perspective review and fallback/tool-boundary artifacts")
    perspective.add_argument("--project", required=True)
    perspective.add_argument("--perspective", action="append", default=[])
    perspective.add_argument("--no-write", action="store_true")

    persona = sub.add_parser("reader-persona-review", help="Create reader persona blind-review artifacts")
    persona.add_argument("--project", required=True)
    persona.add_argument("--no-write", action="store_true")

    workflow = sub.add_parser("run-workflow-engine", help="Run route, multi-perspective review, and gate audit together")
    workflow.add_argument("--project", required=True)
    workflow.add_argument("--no-write", action="store_true")

    review_source_cmd = sub.add_parser("review-source", help="Review source quality")
    review_source_cmd.add_argument("--project", required=True)
    review_source_cmd.add_argument("--source-id", required=True)
    review_source_cmd.add_argument("--quality", choices=["good", "mixed", "poor", "unknown"], required=True)
    review_source_cmd.add_argument("--reason", default="")
    review_source_cmd.add_argument("--reviewer", default="human")

    claim = sub.add_parser("add-claim", help="Add a claim")
    claim.add_argument("--project", required=True)
    claim.add_argument("--text", required=True)
    claim.add_argument("--notes", default="")

    evidence = sub.add_parser("add-evidence", help="Add evidence for a claim")
    evidence.add_argument("--project", required=True)
    evidence.add_argument("--claim-id", required=True)
    evidence.add_argument("--source-id", required=True)
    evidence.add_argument("--quote-or-note", required=True)
    evidence.add_argument("--relation", choices=["supports", "contradicts", "context", "unknown"], default="unknown")
    evidence.add_argument("--confidence", default="unknown")
    evidence.add_argument("--notes", default="")

    fixture = sub.add_parser("run-guarded-e2e-fixture", help="Run the local synthetic guarded research E2E fixture")
    fixture.add_argument("--project", required=True)
    fixture.add_argument("--reviewer", default="guarded-e2e-fixture")
    fixture.add_argument("--stop-after", choices=["intake", "evidence", "blocked", "review", "final"])

    bounded_loop = sub.add_parser(
        "run-bounded-deep-loop",
        help="Run or resume the offline, budget-bounded synthetic research-to-brief action",
    )
    bounded_loop.add_argument("--fixture", required=True)
    bounded_loop.add_argument("--output-root", required=True)
    bounded_loop.add_argument("--closure-run-id")
    bounded_loop.add_argument("--resume", action="store_true")
    bounded_loop.add_argument("--stop-after", choices=["intake", "source_admission", "evidence_analysis", "guarded_synthesis", "article_brief"])
    bounded_loop.add_argument(
        "--synthetic-crash-after",
        choices=["intake", "source_admission", "evidence_analysis", "guarded_synthesis", "article_brief"],
        help="Fixture-only acceptance hook: exit after persisting the selected stage receipt but before checkpoint update",
    )
    bounded_loop.add_argument("--request-finalize", action="store_true")

    offline_brief = sub.add_parser(
        "run-offline-evidence-brief",
        help="Run or resume the bounded offline question-to-evidence-and-brief pack",
    )
    offline_brief.add_argument("--fixture", required=True)
    offline_brief.add_argument("--output-root", required=True)
    offline_brief.add_argument("--closure-run-id")
    offline_brief.add_argument("--resume", action="store_true")
    offline_brief.add_argument(
        "--stop-after",
        choices=["intake", "source_admission", "evidence_analysis", "guarded_synthesis", "article_brief"],
    )
    offline_brief.add_argument(
        "--synthetic-core-crash-after",
        choices=["intake", "source_admission", "evidence_analysis", "guarded_synthesis", "article_brief"],
        help="Fixture-only hook: stop after a core stage receipt is persisted",
    )
    offline_brief.add_argument(
        "--synthetic-projection-crash-after",
        choices=["deliverables", "receipt"],
        help="Fixture-only hook: stop after projection files or their receipt are persisted",
    )

    evidence_review = sub.add_parser("review-evidence", help="Review evidence")
    evidence_review.add_argument("--project", required=True)
    evidence_review.add_argument("--evidence-id", required=True)
    evidence_review.add_argument("--status", choices=["candidate", "verified", "rejected"], required=True)
    evidence_review.add_argument("--relation", choices=["supports", "contradicts", "context", "unknown"])
    evidence_review.add_argument("--confidence")
    evidence_review.add_argument("--notes", default="")
    evidence_review.add_argument("--reviewer", default="human")

    graph_review = sub.add_parser("review-graph-edge", help="Review a graph candidate edge")
    graph_review.add_argument("--project", required=True)
    graph_review.add_argument("--from-id", required=True)
    graph_review.add_argument("--to-id", required=True)
    graph_review.add_argument("--status", choices=["candidate", "verified", "rejected"], required=True)
    graph_review.add_argument("--note", default="")

    list_cmd = sub.add_parser("list", help="List project records")
    list_cmd.add_argument("--project", required=True)
    list_cmd.add_argument("--kind", choices=["sources", "claims", "evidence", "graph", "reviews"], required=True)

    draft = sub.add_parser("draft-answer", help="Render a draft answer")
    draft.add_argument("--project", required=True)
    draft.add_argument("--include-candidate", action="store_true")

    final_answer = sub.add_parser("export-final-answer", help="Export a guarded final answer only after completeness audit passes")
    final_answer.add_argument("--project", required=True)
    final_answer.add_argument("--output-dir")
    final_answer.add_argument("--allow-incomplete", action="store_true")

    research_output = sub.add_parser("export-research-output", help="Export the canonical offline research-output.v1 artifact")
    research_output.add_argument("--project", required=True)
    research_output.add_argument("--output")
    research_output.add_argument("--scope", default="")
    research_output.add_argument("--scope-constraint", action="append", dest="scope_constraints")
    research_output.add_argument("--audience", default="general")
    research_output.add_argument("--requested-output", action="append", dest="requested_outputs")

    overview = sub.add_parser("overview", help="Render project overview")
    overview.add_argument("--project", required=True)

    export = sub.add_parser("export-obsidian", help="Export notes to an Obsidian folder")
    export.add_argument("--project", required=True)
    export.add_argument("--vault", required=True)
    export.add_argument("--folder", default="00_Inbox/AI/问题导向研究流程POC")

    research_pack = sub.add_parser("export-research-pack", help="Export a human-readable research review pack")
    research_pack.add_argument("--project", required=True)
    research_pack.add_argument("--output-dir")

    obsidian_pack = sub.add_parser("export-research-pack-obsidian", help="Copy the research review pack into an Obsidian folder")
    obsidian_pack.add_argument("--project", required=True)
    obsidian_pack.add_argument("--vault", required=True)
    obsidian_pack.add_argument("--folder", default="AI Research/问题导向研究审核包")

    logseq_handoff = sub.add_parser("create-logseq-review-handoff", help="Create a Logseq review handoff file without writing to Logseq")
    logseq_handoff.add_argument("--project", required=True)
    logseq_handoff.add_argument("--output-dir")

    graph = sub.add_parser("write-graph-csv", help="Write graph-candidates.csv")
    graph.add_argument("--project", required=True)

    graph_generate = sub.add_parser("generate-graph-candidates", help="Generate deterministic graph candidate edges")
    graph_generate.add_argument("--project", required=True)

    graph_list = sub.add_parser("list-graph-candidates", help="List graph candidate edges")
    graph_list.add_argument("--project", required=True)
    graph_list.add_argument("--status")
    graph_list.add_argument("--edge-type")

    graph_candidate_review = sub.add_parser("review-graph-candidate", help="Accept or reject a graph candidate edge")
    graph_candidate_review.add_argument("--project", required=True)
    graph_candidate_review.add_argument("--from-id", required=True)
    graph_candidate_review.add_argument("--to-id", required=True)
    graph_candidate_review.add_argument("--status", choices=["candidate", "accepted", "verified", "rejected"], required=True)
    graph_candidate_review.add_argument("--note", default="")
    graph_candidate_review.add_argument("--reviewer", default="human")

    graph_export = sub.add_parser("export-reviewed-graph", help="Export accepted graph edges as Markdown and JSON")
    graph_export.add_argument("--project", required=True)
    graph_export.add_argument("--output-dir")

    video = sub.add_parser("add-video", help="Compatibility interface: register video as a source; processing is delegated")
    video.add_argument("video_path")
    video.add_argument("--project", required=True)
    video.add_argument("--topic", required=True)
    video.add_argument("--transcript-path")
    video.add_argument("--sample-interval", type=float, default=5.0)
    video.add_argument("--max-frames", type=int, default=120)
    video.add_argument("--no-scene-detect", action="store_true")
    video.add_argument("--no-frame-extract", action="store_true")

    sub.add_parser("mcp-tools", help="Print MCP-compatible tool definitions")

    sub.add_parser("config-status", help="Print the unified local runtime config status")

    project_status = sub.add_parser("get-project-status", help="Return agent-facing project status")
    project_status.add_argument("--project", required=True)

    project_dashboard = sub.add_parser("get-project-dashboard", help="Return structured project dashboard data")
    project_dashboard.add_argument("--project", required=True)

    demo = sub.add_parser("build-demo-project", help="Build a deterministic local demo project for cockpit testing")
    demo.add_argument("--project", required=True)

    project_overview = sub.add_parser("get-project-overview", help="Return structured human-readable project overview data")
    project_overview.add_argument("--project", required=True)

    agent_manifest = sub.add_parser("get-agent-manifest", help="Return stable UI/CLI/MCP/API contract for agents")
    agent_manifest.add_argument("--project")

    sub.add_parser("get-tool-health-dashboard", help="Return local tool availability metadata for the research controller")

    bridge_status = sub.add_parser("get-tool-bridge-status", help="Return read-only external tool bridge status for the project")
    bridge_status.add_argument("--project", required=True)
    bridge_status.add_argument("--limit", type=int, default=8)

    bridge_runs = sub.add_parser("list-bridge-runs", help="List normalized external bridge runs")
    bridge_runs.add_argument("--project", required=True)
    bridge_runs.add_argument("--tool")
    bridge_runs.add_argument("--status")
    bridge_runs.add_argument("--limit", type=int, default=20)

    bridge_read = sub.add_parser("read-bridge-run", help="Read one normalized external bridge run")
    bridge_read.add_argument("--project", required=True)
    bridge_read.add_argument("--id", required=True)

    bridge_retry = sub.add_parser("retry-bridge-run-plan", help="Build a read-only retry plan from a bridge run")
    bridge_retry.add_argument("--project", required=True)
    bridge_retry.add_argument("--id", required=True)

    bridge_action_plan = sub.add_parser("plan-bridge-action", help="Create a dry-run bridge action plan and bridge_run")
    bridge_action_plan.add_argument("--project", required=True)
    bridge_action_plan.add_argument("--action", required=True)
    bridge_action_plan.add_argument("--args-json", default="{}")

    bridge_action_run = sub.add_parser("run-bridge-action", help="Run an allowlisted bridge action; dry-run unless --execute is provided")
    bridge_action_run.add_argument("--project", required=True)
    bridge_action_run.add_argument("--action", required=True)
    bridge_action_run.add_argument("--args-json", default="{}")
    bridge_action_run.add_argument("--execute", action="store_true")
    bridge_action_run.add_argument("--timeout-seconds", type=int, default=120)

    enqueue_bridge = sub.add_parser("enqueue-bridge-actions", help="Enqueue structured bridge actions from the current runbook")
    enqueue_bridge.add_argument("--project", required=True)

    completeness = sub.add_parser("audit-completeness", help="Audit deterministic research completeness before final answers")
    completeness.add_argument("--project", required=True)

    cockpit_readiness = sub.add_parser("audit-cockpit-readiness", help="Audit controller capability readiness against the cockpit roadmap")
    cockpit_readiness.add_argument("--project")

    sync_safety = sub.add_parser("audit-sync-safety", help="Audit Git sync safety and local artifact boundaries")
    sync_safety.add_argument("--repo", default=".")

    gate_details = sub.add_parser("get-gate-details", help="Return gate details with concrete blocking records")
    gate_details.add_argument("--project", required=True)
    gate_details.add_argument("--gate-id")

    review_queue = sub.add_parser("get-review-queue", help="Return human review queue")
    review_queue.add_argument("--project", required=True)
    review_queue.add_argument("--item-type")

    next_step = sub.add_parser("run-next-step", help="Run an agent-safe next step or return human-required boundary")
    next_step.add_argument("--project", required=True)
    next_step.add_argument("--gate-id", required=True)
    next_step.add_argument("--no-write", action="store_true")

    artifact = sub.add_parser("read-workflow-artifact", help="Read a workflow artifact by id")
    artifact.add_argument("--project", required=True)
    artifact.add_argument("--artifact-id", required=True)
    artifact.add_argument("--format", choices=["markdown", "json"], default="markdown")

    runbook = sub.add_parser("build-agent-runbook", help="Build the next safe agent runbook from current dashboard state")
    runbook.add_argument("--project", required=True)

    enqueue_runbook = sub.add_parser("enqueue-runbook-tasks", help="Enqueue agent-safe tasks from the current runbook")
    enqueue_runbook.add_argument("--project", required=True)

    list_queue = sub.add_parser("list-work-queue", help="List queued human and agent tasks")
    list_queue.add_argument("--project", required=True)
    list_queue.add_argument("--status")

    update_queue = sub.add_parser("update-work-queue-item", help="Update one work queue item status")
    update_queue.add_argument("--project", required=True)
    update_queue.add_argument("--id", required=True)
    update_queue.add_argument("--status", choices=["pending", "running", "done", "failed", "needs_human"], required=True)
    update_queue.add_argument("--note", default="")

    run_queue_item = sub.add_parser("run-work-queue-item", help="Preview or execute one work queue tool action; dry-run by default")
    run_queue_item.add_argument("--project", required=True)
    run_queue_item.add_argument("--id", required=True)
    run_queue_item.add_argument("--execute", action="store_true")
    run_queue_item.add_argument("--timeout-seconds", type=int, default=60)

    tool_action = sub.add_parser("run-local-tool-action", help="Plan or execute a whitelisted local-tool action; dry-run by default")
    tool_action.add_argument("tool_id")
    tool_action.add_argument("action")
    tool_action.add_argument("--args-json", default="{}")
    tool_action.add_argument("--execute", action="store_true")
    tool_action.add_argument("--timeout-seconds", type=int, default=60)

    inbox_add = sub.add_parser("add-source-inbox-item", help="Add a candidate material item to the source inbox")
    inbox_add.add_argument("--project", required=True)
    inbox_add.add_argument("--kind", required=True)
    inbox_add.add_argument("--title", required=True)
    inbox_add.add_argument("--location", default="")
    inbox_add.add_argument("--url", default="")
    inbox_add.add_argument("--path", default="")
    inbox_add.add_argument("--source-tool", default="")
    inbox_add.add_argument("--quality-hint", default="unknown")
    inbox_add.add_argument("--notes", default="")

    inbox_list = sub.add_parser("list-source-inbox", help="List source inbox candidate materials")
    inbox_list.add_argument("--project", required=True)
    inbox_list.add_argument("--status")

    inbox_import = sub.add_parser("import-source-inbox-item", help="Import one source inbox item as a candidate source")
    inbox_import.add_argument("--project", required=True)
    inbox_import.add_argument("--id", required=True)
    inbox_import.add_argument("--source-quality", default="unknown")

    inbox_reject = sub.add_parser("reject-source-inbox-item", help="Reject one source inbox item")
    inbox_reject.add_argument("--project", required=True)
    inbox_reject.add_argument("--id", required=True)
    inbox_reject.add_argument("--note", default="")

    mcp_call = sub.add_parser("mcp-call", help="Call one MCP-compatible tool with a JSON argument file or JSON string")
    mcp_call.add_argument("tool")
    mcp_call.add_argument("arguments_json")

    video_knowledge = sub.add_parser("video-knowledge", help="Bridge to extracted video-knowledge-pipeline CLI")
    video_knowledge.add_argument("--root", help="video-knowledge-pipeline root; defaults to VIDEO_KNOWLEDGE_PIPELINE_ROOT or a sibling checkout")
    video_knowledge.add_argument("--timeout-seconds", type=int, default=0)
    video_knowledge.add_argument("video_knowledge_args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/video-knowledge.ps1")

    video_plan = sub.add_parser("plan-video-knowledge-run", help="Plan a video-knowledge-pipeline local video run without executing it")
    video_plan.add_argument("media_path")
    video_plan.add_argument("workspace")
    video_plan.add_argument("--title", default="")
    video_plan.add_argument("--max-frames", type=int, default=80)
    video_plan.add_argument("--no-build-initial-bundle", action="store_true")
    video_plan.add_argument("--root", help="video-knowledge-pipeline root; defaults to VIDEO_KNOWLEDGE_PIPELINE_ROOT or a sibling checkout")
    video_plan.add_argument("--project", help="Optional research project root for recording a bridge run")

    video_check = sub.add_parser("check-video-run-artifacts", help="Check expected video-knowledge-pipeline review bundle artifacts")
    video_check.add_argument("bundle_dir")

    video_import = sub.add_parser("import-video-knowledge-artifacts", help="Import reviewed video-knowledge-pipeline artifacts as candidate source/evidence")
    video_import.add_argument("bundle_dir")
    video_import.add_argument("--project", required=True)
    video_import.add_argument("--title", default="")
    video_import.add_argument("--claim-id", default="")
    video_import.add_argument("--source-quality", default="unknown")

    web = sub.add_parser("run-web", help=f"Run the local human UI; defaults come from {RUNTIME_CONFIG_PATH}")
    web.add_argument("--host", default=None, help=f"Override configured host; default: {web_host()}")
    web.add_argument("--port", type=int, default=None, help=f"Override configured port; default: {web_port()}")
    web.add_argument("--open-browser", action="store_true")

    model_assist = sub.add_parser(
        "model-assist",
        help="Delegate candidate-only planning or guarded-answer assistance through ARW",
    )
    model_assist.add_argument("--project", required=True)
    model_assist.add_argument("--profile", required=True, help="provider-profile.v1 JSON path or object")
    model_assist.add_argument("--route", required=True, help="route_plan.v1 JSON path or object")
    model_assist.add_argument("--consent", required=True, help="consent_manifest.v2 JSON path or object")
    model_assist.add_argument(
        "--purpose",
        required=True,
        choices=["planning", "guarded_answer", "visual_evidence_candidate"],
    )
    model_assist.add_argument("--request-id", required=True)
    model_assist.add_argument("--max-cost-usd", required=True, type=float)

    embedding_assist = sub.add_parser(
        "embedding-assist",
        help="Delegate synthetic owner-receipt validation through ARW without executing a model",
    )
    embedding_assist.add_argument("--project", required=True)
    embedding_assist.add_argument("--artifact", action="append", required=True)
    embedding_assist.add_argument("--mime-type", action="append", dest="mime_types")
    embedding_assist.add_argument("--purpose", required=True)
    embedding_assist.add_argument("--request-id", required=True)
    embedding_assist.add_argument("--receipt")

    capability_closure = sub.add_parser(
        "gateway-capability-closure",
        help="Run or resume the fully synthetic QRP/ARW Gateway capability closure",
    )
    capability_closure.add_argument("--output-root", required=True)
    capability_closure.add_argument("--closure-run-id", required=True)
    capability_closure.add_argument("--closure-schema", required=True)
    capability_closure.add_argument("--source-inventory", required=True)
    capability_closure.add_argument("--owner-routing", required=True)
    capability_closure.add_argument("--tool-registry", required=True)
    capability_closure.add_argument("--resume", action="store_true")
    return parser


def _dispatch(args: argparse.Namespace) -> object:
    if args.command == "init":
        return init_project(args.project, args.research_question)
    if args.command == "add-source":
        return add_source(args.project, title=args.title, url=args.url or "", path=args.path or "", source_type=args.source_type, quality=args.quality, notes=args.notes)
    if args.command == "import-sources":
        return import_sources(args.project, args.path, default_quality=args.default_quality)
    if args.command == "plan-research":
        return build_research_plan(args.project, question=args.question, write=not args.no_write, add_claims=args.add_claims)
    if args.command == "read-research-plan":
        return read_research_plan(args.project)
    if args.command == "analyze-research-gaps":
        return analyze_research_gaps(args.project, query=args.query, max_queries_per_round=args.max_queries_per_round)
    if args.command == "research-loop":
        return run_research_loop(
            args.project,
            query=args.query,
            mode=args.mode,
            rounds=args.rounds,
            max_results=args.max_results,
            max_queries_per_round=args.max_queries_per_round,
            no_network=args.no_network,
            fetch=not args.no_fetch,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            status_timeout_seconds=args.status_timeout_seconds,
        )
    if args.command == "list-research-loops":
        return list_research_loops(args.project, limit=args.limit)
    if args.command == "read-research-loop":
        return read_research_loop(args.project, args.id)
    if args.command == "export-research-loop-review-pack":
        return export_research_loop_review_pack(args.project, loop_id=args.id, output_dir=args.output_dir)
    if args.command == "ai-research-status":
        return ai_research_status(args.base_url)
    if args.command == "deep-research":
        status = ai_research_status(args.base_url, timeout_seconds=args.status_timeout_seconds)
        ai_status = _deep_research_ai_status(status)
        if not _ai_research_bridge_ready(status):
            return {
                "ok": False,
                "schema": "question_research_deep_research_run.v1",
                "tool": "ai-research-workflow",
                "project": args.project,
                "query": args.query,
                "ai_research_status": ai_status,
                "live_ok": bool(ai_status.get("live_ok")),
                "available": bool(ai_status.get("available")),
                "status": str(ai_status.get("status") or "service_unreachable"),
                "job_id": "",
                "run_id": "",
                "fallback_used": False,
                "failure_reason": "bridge_down",
                "preflight": status,
                "error": "ai-research-workflow is unreachable; deep-research did not run.",
                "next_action": status.get("next_action") or "Start ai-research-workflow and retry deep-research.",
                "fallback_policy": "Do not silently fall back to manual web search; report the bridge failure or use another explicitly approved route.",
            }
        run = run_ai_research_agent_research(
            args.project,
            query=args.query,
            mode=args.mode,
            max_results=args.max_results,
            no_network=args.no_network,
            fetch=not args.no_fetch,
            import_results=True,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
        )
        return {
            "ok": bool(run.get("ok")),
            "schema": "question_research_deep_research_run.v1",
            "tool": "question-research-poc",
            "delegated_tool": "ai-research-workflow",
            "ai_research_status": ai_status,
            "live_ok": bool(status.get("live_ok", status.get("ok"))),
            "available": bool(status.get("available", status.get("ok"))),
            "status": str(status.get("status") or ("available" if status.get("ok") else "service_unreachable")),
            "job_id": str(run.get("job_id") or ""),
            "run_id": str(run.get("run_id") or ""),
            "fallback_used": bool(run.get("fallback_used", False)),
            "failure_reason": str(run.get("failure_reason") or ""),
            "preflight": status,
            "run": run,
            "human_review_required": True,
            "next_action": "Review imported candidate sources/evidence in QRP; do not treat candidates as verified.",
        }
    if args.command == "research-search":
        return run_ai_research_search(
            args.project,
            query=args.query,
            mode=args.mode,
            max_results=args.max_results,
            deep=args.deep,
            no_network=args.no_network,
            fetch=not args.no_fetch,
            import_results=args.import_results,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "plan-ai-research-search":
        return plan_ai_research_search(
            args.project,
            query=args.query,
            mode=args.mode,
            max_results=args.max_results,
            deep=args.deep,
            no_network=args.no_network,
            fetch=not args.no_fetch,
            import_results=args.import_results,
            base_url=args.base_url,
        )
    if args.command == "import-ai-research-result":
        return import_ai_research_result(
            args.project,
            args.path,
            import_sources=not args.no_sources,
            import_claims=not args.no_claims,
            import_evidence=not args.no_evidence,
        )
    if args.command == "vane-perplexica-status":
        return vane_perplexica_status(args.base_url)
    if args.command == "vane-perplexica-search":
        return run_vane_perplexica_search(
            args.project,
            query=args.query,
            sources=args.sources,
            optimization_mode=args.optimization_mode,
            base_url=args.base_url,
            chat_provider_id=args.chat_provider_id,
            chat_model_key=args.chat_model_key,
            embedding_provider_id=args.embedding_provider_id,
            embedding_model_key=args.embedding_model_key,
            system_instructions=args.system_instructions,
            import_results=args.import_results,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "plan-vane-perplexica-search":
        return plan_vane_perplexica_search(
            args.project,
            query=args.query,
            sources=args.sources,
            optimization_mode=args.optimization_mode,
            base_url=args.base_url,
            chat_provider_id=args.chat_provider_id,
            chat_model_key=args.chat_model_key,
            embedding_provider_id=args.embedding_provider_id,
            embedding_model_key=args.embedding_model_key,
            system_instructions=args.system_instructions,
            import_results=args.import_results,
        )
    if args.command == "import-vane-perplexica-result":
        return import_vane_perplexica_result(args.project, args.path, import_sources=not args.no_sources)
    if args.command == "plan-external-researcher":
        return plan_external_researcher_session(
            args.project,
            question=args.question,
            clarification_answers=args.clarification_answers,
            providers=args.providers,
            source_policy=args.source_policy,
            output_language=args.output_language,
        )
    if args.command == "answer-external-followup":
        return answer_external_researcher_followup(
            args.project,
            followup_question=args.followup_question,
            manual_answer=args.manual_answer,
            original_question=args.original_question,
            source_policy=args.source_policy,
            auto_after_seconds=args.auto_after_seconds,
        )
    if args.command == "import-external-researcher-report":
        return import_external_researcher_report(
            args.project,
            provider=args.provider,
            report_text=args.report_text,
            prompt_text=args.prompt_text,
            report_url=args.report_url,
            notes=args.notes,
            import_as_source=not args.no_source,
        )
    if args.command == "list-external-researcher-reports":
        return list_external_researcher_reports(args.project)
    if args.command == "export-external-researcher-bundle":
        return export_external_researcher_bundle(args.project, output_dir=args.output_dir)
    if args.command == "plan-external-researcher-automation":
        return plan_external_researcher_automation(
            args.project,
            question=args.question,
            clarification_answers=args.clarification_answers,
            providers=args.providers,
            source_policy=args.source_policy,
            output_language=args.output_language,
            profile_config_path=args.profile_config_path,
            followup_wait_seconds=args.followup_wait_seconds,
            max_wait_seconds=args.max_wait_seconds,
        )
    if args.command == "run-external-researcher-automation":
        return run_external_researcher_automation(
            args.project,
            automation_plan=args.automation_plan,
            question=args.question,
            clarification_answers=args.clarification_answers,
            providers=args.providers,
            source_policy=args.source_policy,
            output_language=args.output_language,
            profile_config_path=args.profile_config_path,
            followup_wait_seconds=args.followup_wait_seconds,
            max_wait_seconds=args.max_wait_seconds,
            headless=args.headless,
            import_as_source=not args.no_source,
            dry_run=args.dry_run,
        )
    if args.command == "check-external-researcher-automation":
        return check_external_researcher_automation_profiles(
            args.project,
            automation_plan=args.automation_plan,
            question=args.question,
            clarification_answers=args.clarification_answers,
            providers=args.providers,
            source_policy=args.source_policy,
            output_language=args.output_language,
            profile_config_path=args.profile_config_path,
            followup_wait_seconds=args.followup_wait_seconds,
            max_wait_seconds=args.max_wait_seconds,
            live=args.live,
            headless=args.headless,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "run-omnigent-external-research-poc":
        return run_omnigent_external_research_poc(
            args.project,
            question=args.question,
            clarification_answers=args.clarification_answers,
            providers=args.providers,
            source_policy=args.source_policy,
            output_language=args.output_language,
            profile_config_path=args.profile_config_path,
            followup_wait_seconds=args.followup_wait_seconds,
            max_wait_seconds=args.max_wait_seconds,
            headless=args.headless,
            import_as_source=not args.no_source,
            dry_run=not args.live,
        )
    if args.command == "prepare-external-researcher-login-profiles":
        return prepare_external_researcher_login_profiles(
            args.project,
            providers=args.providers,
            automation_plan=args.automation_plan,
            profile_config_path=args.profile_config_path,
            keep_open_seconds=args.keep_open_seconds,
            timeout_seconds=args.timeout_seconds,
            headless=args.headless,
            live=args.live,
        )
    if args.command == "write-external-researcher-profile-template":
        return write_external_researcher_profile_template(args.project, output_path=args.output_path)
    if args.command == "fetch-source-content":
        return fetch_source_content(
            args.project,
            source_id=args.source_id,
            url=args.url,
            title=args.title,
            claim_id=args.claim_id,
            fetch_profile=args.fetch_profile,
            backend=args.backend,
            extractor=args.extractor,
            use_browser=args.browser,
            include_raw=args.include_raw,
            timeout_seconds=args.timeout_seconds,
            import_source=not args.no_import_source,
            create_candidate_evidence=args.create_candidate_evidence,
        )
    if args.command == "plan-fetch-source-content":
        return plan_fetch_source_content(
            args.project,
            source_id=args.source_id,
            url=args.url,
            title=args.title,
            claim_id=args.claim_id,
            fetch_profile=args.fetch_profile,
            backend=args.backend,
            extractor=args.extractor,
            use_browser=args.browser,
            include_raw=args.include_raw,
            timeout_seconds=args.timeout_seconds,
            import_source=not args.no_import_source,
            create_candidate_evidence=args.create_candidate_evidence,
        )
    if args.command == "route-research-task":
        return route_research_task(args.project, question=args.question, material_hint=args.material_hint, write=not args.no_write)
    if args.command == "audit-gates":
        return audit_research_gates(args.project, target_stage=args.target_stage, write=not args.no_write)
    if args.command == "multi-perspective-review":
        return run_multi_perspective_review(args.project, perspectives=args.perspective or None, write=not args.no_write)
    if args.command == "reader-persona-review":
        return run_reader_persona_review(args.project, write=not args.no_write)
    if args.command == "run-workflow-engine":
        return run_workflow_engine(args.project, write=not args.no_write)
    if args.command == "review-source":
        return review_source(args.project, source_id=args.source_id, quality=args.quality, reason=args.reason, reviewer=args.reviewer)
    if args.command == "add-claim":
        return add_claim(args.project, text=args.text, notes=args.notes)
    if args.command == "add-evidence":
        return add_evidence(args.project, claim_id=args.claim_id, source_id=args.source_id, quote_or_note=args.quote_or_note, relation=args.relation, confidence=args.confidence, notes=args.notes)
    if args.command == "run-guarded-e2e-fixture":
        return run_guarded_e2e_fixture(args.project, reviewer=args.reviewer, stop_after=args.stop_after)
    if args.command == "run-bounded-deep-loop":
        return run_bounded_deep_loop(
            args.fixture,
            args.output_root,
            closure_run_id=args.closure_run_id,
            resume=args.resume,
            stop_after=args.stop_after,
            crash_after=args.synthetic_crash_after,
            request_finalize=args.request_finalize,
        )
    if args.command == "run-offline-evidence-brief":
        return run_offline_evidence_brief(
            args.fixture,
            args.output_root,
            closure_run_id=args.closure_run_id,
            resume=args.resume,
            stop_after=args.stop_after,
            core_crash_after=args.synthetic_core_crash_after,
            projection_crash_after=args.synthetic_projection_crash_after,
        )
    if args.command == "review-evidence":
        return review_evidence(args.project, evidence_id=args.evidence_id, status=args.status, relation=args.relation, confidence=args.confidence, notes=args.notes, reviewer=args.reviewer)
    if args.command == "review-graph-edge":
        return review_graph_edge(args.project, from_id=args.from_id, to_id=args.to_id, status=args.status, note=args.note)
    if args.command == "list":
        return list_records(args.project, args.kind)
    if args.command == "draft-answer":
        return draft_answer(args.project, include_candidate=args.include_candidate)
    if args.command == "export-final-answer":
        return export_final_answer(args.project, output_dir=args.output_dir, allow_incomplete=args.allow_incomplete)
    if args.command == "export-research-output":
        return export_research_output(
            args.project,
            output_path=args.output,
            scope=args.scope,
            audience=args.audience,
            requested_outputs=args.requested_outputs,
            scope_constraints=args.scope_constraints,
        )
    if args.command == "overview":
        return render_project_overview(args.project)
    if args.command == "export-obsidian":
        return export_obsidian(args.project, args.vault, folder=args.folder)
    if args.command == "export-research-pack":
        return export_research_pack(args.project, output_dir=args.output_dir)
    if args.command == "export-research-pack-obsidian":
        return export_research_pack_to_obsidian(args.project, args.vault, folder=args.folder)
    if args.command == "create-logseq-review-handoff":
        return create_logseq_review_handoff(args.project, output_dir=args.output_dir)
    if args.command == "write-graph-csv":
        return {"path": str(write_graph_csv(args.project))}
    if args.command == "generate-graph-candidates":
        return generate_graph_candidates(args.project)
    if args.command == "list-graph-candidates":
        return list_graph_candidates(args.project, status=args.status, edge_type=args.edge_type)
    if args.command == "review-graph-candidate":
        return review_graph_candidate(args.project, from_id=args.from_id, to_id=args.to_id, status=args.status, note=args.note, reviewer=args.reviewer)
    if args.command == "export-reviewed-graph":
        return export_reviewed_graph(args.project, output_dir=args.output_dir)
    if args.command == "add-video":
        return add_video(
            args.project,
            args.video_path,
            topic=args.topic,
            transcript_path=args.transcript_path,
            sample_interval=args.sample_interval,
            max_frames=args.max_frames,
            detect_scenes=not args.no_scene_detect,
            extract_frames=not args.no_frame_extract,
        )
    if args.command == "mcp-tools":
        from .mcp_server import list_mcp_tools

        return list_mcp_tools()
    if args.command == "config-status":
        config = load_runtime_config()
        return {
            "ok": True,
            "runtime_config": str(RUNTIME_CONFIG_PATH),
            "web": {
                "host": web_host(config),
                "port": web_port(config),
                "url": web_url(config),
            },
            "project": {
                "default_root": str(default_project_root(config)),
            },
        }
    if args.command == "get-project-status":
        return get_project_status(args.project)
    if args.command == "get-project-dashboard":
        return get_project_dashboard(args.project)
    if args.command == "build-demo-project":
        return build_demo_project(args.project)
    if args.command == "get-project-overview":
        return get_project_overview(args.project)
    if args.command == "get-agent-manifest":
        return build_agent_manifest(args.project)
    if args.command == "get-tool-health-dashboard":
        return get_tool_health_dashboard()
    if args.command == "get-tool-bridge-status":
        return build_tool_bridge_status(args.project, limit=args.limit)
    if args.command == "list-bridge-runs":
        return list_bridge_runs(args.project, tool=args.tool, status=args.status, limit=args.limit)
    if args.command == "read-bridge-run":
        return read_bridge_run(args.project, args.id)
    if args.command == "retry-bridge-run-plan":
        return retry_bridge_run_plan(args.project, args.id)
    if args.command == "plan-bridge-action":
        return plan_bridge_action(args.project, args.action, args=_json_arg(args.args_json))
    if args.command == "run-bridge-action":
        return run_bridge_action(args.project, args.action, args=_json_arg(args.args_json), execute=args.execute, timeout_seconds=args.timeout_seconds)
    if args.command == "enqueue-bridge-actions":
        return enqueue_bridge_actions(args.project)
    if args.command == "audit-completeness":
        return audit_research_completeness(args.project)
    if args.command == "audit-cockpit-readiness":
        return audit_cockpit_readiness(args.project)
    if args.command == "audit-sync-safety":
        return audit_sync_safety(args.repo)
    if args.command == "get-gate-details":
        return get_gate_details(args.project, gate_id=args.gate_id)
    if args.command == "get-review-queue":
        return get_review_queue(args.project, item_type=args.item_type)
    if args.command == "run-next-step":
        return run_next_step(args.project, args.gate_id, write=not args.no_write)
    if args.command == "read-workflow-artifact":
        return read_workflow_artifact(args.project, args.artifact_id, format=args.format)
    if args.command == "build-agent-runbook":
        return build_agent_runbook(args.project)
    if args.command == "enqueue-runbook-tasks":
        return enqueue_runbook_tasks(args.project)
    if args.command == "list-work-queue":
        return get_work_queue(args.project, status=args.status)
    if args.command == "update-work-queue-item":
        return update_task_status(args.project, args.id, args.status, note=args.note)
    if args.command == "run-work-queue-item":
        return run_work_queue_item(args.project, args.id, execute=args.execute, timeout_seconds=args.timeout_seconds)
    if args.command == "run-local-tool-action":
        return run_local_tool_action(args.tool_id, args.action, args=_json_arg(args.args_json), execute=args.execute, timeout_seconds=args.timeout_seconds)
    if args.command == "add-source-inbox-item":
        return add_inbox_item(args.project, kind=args.kind, title=args.title, location=args.location, url=args.url, path=args.path, source_tool=args.source_tool, quality_hint=args.quality_hint, notes=args.notes)
    if args.command == "list-source-inbox":
        return get_source_inbox(args.project, status=args.status)
    if args.command == "import-source-inbox-item":
        return import_inbox_item_as_source(args.project, args.id, source_quality=args.source_quality)
    if args.command == "reject-source-inbox-item":
        return reject_inbox_item(args.project, args.id, note=args.note)
    if args.command == "mcp-call":
        from .mcp_server import call_mcp_tool

        return call_mcp_tool(args.tool, _json_arg(args.arguments_json))
    if args.command == "video-knowledge":
        return run_video_knowledge_tool(args.video_knowledge_args, root=args.root, timeout_seconds=args.timeout_seconds)
    if args.command == "plan-video-knowledge-run":
        return plan_video_knowledge_run(
            args.media_path,
            args.workspace,
            title=args.title,
            max_frames=args.max_frames,
            build_initial_bundle=not args.no_build_initial_bundle,
            root=args.root,
            project_root=args.project,
        )
    if args.command == "check-video-run-artifacts":
        return check_video_run_artifacts(args.bundle_dir)
    if args.command == "import-video-knowledge-artifacts":
        return import_video_knowledge_artifacts(
            args.project,
            args.bundle_dir,
            title=args.title,
            claim_id=args.claim_id,
            source_quality=args.source_quality,
        )
    if args.command == "model-assist":
        try:
            profile = _json_arg(args.profile)
            route = _json_arg(args.route)
            consent = _json_arg(args.consent)
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                "schema": "question_research_poc.model_assist_bridge_status.v1",
                "ok": False,
                "status": "blocked",
                "error_class": "input_contract_unavailable",
                "error_message": "QRP model-assist input could not be loaded",
                "research_truth_effect": "none",
                "evidence_status_change": "none",
                "human_review_required": True,
                "automatic_fallback_allowed": False,
            }
        return run_gateway_model_assist(
            args.project,
            profile=profile,
            route=route,
            consent=consent,
            purpose=args.purpose,
            request_id=args.request_id,
            max_estimated_cost_usd=args.max_cost_usd,
        )
    if args.command == "embedding-assist":
        return run_gateway_embedding_candidate(
            args.project,
            artifact_paths=args.artifact,
            mime_types=args.mime_types,
            purpose=args.purpose,
            request_id=args.request_id,
            receipt_path=args.receipt,
        )
    if args.command == "gateway-capability-closure":
        return run_gateway_capability_closure(
            output_root=args.output_root,
            closure_run_id=args.closure_run_id,
            closure_schema_path=args.closure_schema,
            source_inventory_path=args.source_inventory,
            owner_routing_path=args.owner_routing,
            tool_registry_path=args.tool_registry,
            resume=args.resume,
        )
    if args.command == "run-web":
        return run_web_ui(host=args.host, port=args.port, open_browser=args.open_browser)
    raise ValueError(f"unknown command: {args.command}")


def _json_arg(value: str) -> dict:
    path = Path(value).expanduser()
    data = json.loads(path.read_text(encoding="utf-8") if path.exists() else value)
    if not isinstance(data, dict):
        raise ValueError("arguments_json must be a JSON object")
    return data


def _deep_research_ai_status(status: dict) -> dict:
    return {
        "metadata_available": bool(status.get("metadata_available", status.get("discovery"))),
        "live_ok": bool(status.get("live_ok", status.get("ok"))),
        "available": bool(status.get("available", status.get("ok"))),
        "status": str(status.get("status") or ("available" if status.get("ok") else "service_unreachable")),
        "base_url": str(status.get("base_url") or ""),
        "error": str(status.get("error") or ""),
        "next_action": str(status.get("next_action") or ""),
    }


def _ai_research_bridge_ready(status: dict) -> bool:
    return bool(status.get("metadata_available") and status.get("live_ok", status.get("ok")) and status.get("available", status.get("ok")))


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return value.__dict__
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
