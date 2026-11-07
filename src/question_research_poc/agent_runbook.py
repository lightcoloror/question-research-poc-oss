from __future__ import annotations

from pathlib import Path
from typing import Any

from .dashboard import build_project_dashboard
from .local_tool_health import build_local_tool_health_dashboard
from .orchestrator import list_records
from .research_gaps import ACTIONABLE_STATUS, analyze_research_gaps
from .review_state import build_review_queue, build_workflow_payload
from .tool_bridge_status import build_tool_bridge_status


RUNBOOK_SCHEMA = "question_research_agent_runbook.v1"


def build_agent_runbook(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    workflow = build_workflow_payload(project_root)
    review_queue = build_review_queue(project_root)
    dashboard = build_project_dashboard(project_root, workflow=workflow, review_queue=review_queue)
    stage = dashboard.get("stage_detail", {}) if isinstance(dashboard.get("stage_detail"), dict) else {}
    local_tools = build_local_tool_health_dashboard()
    bridge_status = build_tool_bridge_status(project_root, limit=3)
    sources = list_records(project_root, "sources") if project_root.exists() else []
    commands = _commands_for_state(project_root, stage, dashboard, workflow, review_queue, sources, bridge_status)
    human_tasks = _human_tasks(review_queue, stage)
    boundaries = [
        "Agent 可以生成计划、搜索任务、抓取计划、候选证据、视频处理计划和导出包。",
        "Agent 不得把候选证据自动升级为 verified evidence。",
        "Agent 不得替代人工判定来源质量、证据可信度或最终结论强度。",
        "Logseq 写回必须经过 WebUI/审核包人工确认，不允许绕过审核直接写入。",
        "外部工具只通过桥接入口调用，不在 question-research-poc 复制底层实现。",
    ]
    result = {
        "ok": bool(dashboard.get("ok")),
        "schema": RUNBOOK_SCHEMA,
        "root": str(project_root),
        "stage": stage,
        "review_queue_count": len(review_queue),
        "commands": commands,
        "human_tasks": human_tasks,
        "operator_boundaries": boundaries,
        "local_tools": local_tools,
        "bridge_status": {
            "backend_mode": bridge_status.get("backend_mode"),
            "backend_summary": bridge_status.get("backend_summary"),
            "fallback_scope": bridge_status.get("fallback_scope", []),
        },
    }
    result["markdown"] = render_agent_runbook_markdown(result)
    return result


def render_agent_runbook_markdown(runbook: dict[str, Any]) -> str:
    stage = runbook.get("stage", {}) if isinstance(runbook.get("stage"), dict) else {}
    lines = [
        f"# Agent 下一步 Runbook",
        "",
        f"- Project: `{runbook.get('root', '')}`",
        f"- Stage: `{stage.get('stage_id', 'unknown')}` {stage.get('stage_label', '')}",
        f"- Blocking gate: `{stage.get('blocking_gate', '')}`",
        f"- Review queue: {runbook.get('review_queue_count', 0)}",
        "",
        "## Stage Reasons",
        "",
    ]
    reasons = stage.get("reasons", []) if isinstance(stage, dict) else []
    lines.extend(f"- {reason}" for reason in reasons) if reasons else lines.append("- No stage reasons available.")
    lines.extend(["", "## Agent Commands", ""])
    commands = runbook.get("commands", [])
    if commands:
        for command in commands:
            lines.append(f"### {command.get('title', '')}")
            lines.append(f"- Boundary: {command.get('boundary', '')}")
            lines.append(f"- Why: {command.get('why', '')}")
            lines.append("")
            lines.append("```powershell")
            lines.append(command.get("command", ""))
            lines.append("```")
            lines.append("")
    else:
        lines.append("- No safe agent command is currently available.")
    lines.extend(["## Human Tasks", ""])
    tasks = runbook.get("human_tasks", [])
    lines.extend(f"- `{task.get('item_type', '')}` {task.get('title', '')}: {task.get('action', '')}" for task in tasks) if tasks else lines.append("- No human tasks currently listed.")
    lines.extend(["", "## Operator Boundaries", ""])
    lines.extend(f"- {item}" for item in runbook.get("operator_boundaries", []))
    return "\n".join(lines).rstrip() + "\n"


def _commands_for_state(
    project_root: Path,
    stage: dict[str, Any],
    dashboard: dict[str, Any],
    workflow: dict[str, Any],
    review_queue: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    bridge_status: dict[str, Any],
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    root_arg = _ps_quote(str(project_root))
    stage_id = str(stage.get("stage_id", ""))
    blocking_gate = str(stage.get("blocking_gate", ""))
    backend_mode = str(bridge_status.get("backend_mode") or "blocked")
    backend_summary = str(bridge_status.get("backend_summary") or "")
    gap_analysis = _safe_gap_analysis(project_root)
    actionable_gaps = [gap for gap in gap_analysis.get("gaps", []) if gap.get("status") == ACTIONABLE_STATUS]
    review_only_gaps = [gap for gap in gap_analysis.get("gaps", []) if gap.get("status") != ACTIONABLE_STATUS]
    if stage_id == "not_initialized":
        commands.append(_command("Create project", f".\\scripts\\research-poc.ps1 init \"研究问题\" --project {root_arg}", "Needs a confirmed research question.", "Requires human to provide the actual question."))
        return commands
    commands.append(
        _command(
            "Analyze research gaps",
            f".\\scripts\\research-poc.ps1 analyze-research-gaps --project {root_arg} --max-queries-per-round 3",
            "Classify actionable search gaps versus review-only gaps before running another research round.",
            "Read-only gap diagnosis. It does not run live search or import evidence.",
        )
    )
    if stage_id == "question_defined" or blocking_gate == "research_plan_present":
        commands.append(_command("Build research plan", f".\\scripts\\research-poc.ps1 plan-research --project {root_arg} --add-claims", "Project has a question but no research plan.", "Agent-safe; creates plan and initial claims."))
    if stage_id in {"research_plan_ready", "question_defined"} or blocking_gate == "sources_present":
        if backend_mode == "full_research":
            commands.append(
                _command(
                    "Codex deep research",
                    f".\\scripts\\research-poc.ps1 deep-research --project {root_arg} --mode academic --max-results 8",
                    "Use this when the user asks for deep search/deep research and expects ai-research-workflow to run.",
                    "Preflights ai-research-workflow, calls /v1/agent/research, imports candidates, and keeps evidence behind human review gates.",
                    tool_action={"kind": "bridge_action", "action": "ai_research_search", "args": {"deep": True, "import_results": True, "mode": "academic", "max_results": 8}},
                )
            )
            if actionable_gaps:
                commands.append(
                    _command(
                        "Automatic research loop",
                        f".\\scripts\\research-poc.ps1 research-loop --project {root_arg} --mode academic --rounds 3 --max-results 8 --max-queries-per-round 3",
                        "Use this only when gap analysis has actionable search gaps after first-round research.",
                        "Runs gap analysis plus follow-up ai-research jobs; outputs remain candidate-only and human-review-gated.",
                        tool_action={
                            "kind": "research_loop",
                            "args": {"mode": "academic", "rounds": 3, "max_results": 8, "max_queries_per_round": 3},
                        },
                    )
                )
            if review_only_gaps and not actionable_gaps:
                commands.append(
                    _command(
                        "Review queue instead of more search",
                        f".\\scripts\\research-poc.ps1 get-review-queue --project {root_arg}",
                        "Current gaps are review-only; more search would add noise before human source/evidence review.",
                        "Read-only review queue inspection. Agent must not auto-approve source quality or evidence.",
                    )
                )
        else:
            commands.append(
                _command(
                    "Backend degraded: pause live AI research search",
                    ".\\scripts\\research-poc.ps1 get-tool-bridge-status --project " + root_arg,
                    backend_summary or "Search backend is degraded; do not run ai_research_search live.",
                    "Use cached/local-only fallback until ai-research-workflow and SearXNG readiness are restored.",
                )
            )
        commands.append(_command("Plan AI research search", f".\\scripts\\research-poc.ps1 plan-ai-research-search --project {root_arg} --import-results", "Sources are missing or insufficient.", "Read-only plan; execution/import remains explicit."))
        if backend_mode == "full_research":
            commands.append(
                _command(
                    "Bridge action: AI research search",
                    f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action ai_research_search --args-json '{{\"deep\":true,\"import_results\":true}}'",
                    "Sources are missing or insufficient; queue a delegated search action for explicit dry-run/live execution.",
                    "Default queue execution is dry-run. Live execution must be explicit and imported items remain candidate.",
                    tool_action={"kind": "bridge_action", "action": "ai_research_search", "args": {"deep": True, "import_results": True}},
                )
            )
        commands.append(
            _command(
                "Bridge action: external researcher plan",
                f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action external_researcher_plan --args-json '{{}}'",
                "Sources are missing or insufficient; prepare a copyable prompt for external Deep Research providers.",
                "Plan/prompt only. Provider reports remain candidate context after manual import.",
                tool_action={"kind": "bridge_action", "action": "external_researcher_plan", "args": {}},
            )
        )
        commands.append(
            _command(
                "Check AI research service",
                f".\\scripts\\research-poc.ps1 run-local-tool-action ai-research-workflow service_status",
                "Confirm the delegated search service is reachable before running search.",
                "Allowlisted status check only; does not run a search.",
                tool_action={"tool_id": "ai-research-workflow", "action": "service_status", "args": {}},
            )
        )
        commands.append(_command("Inspect bridge runs", f".\\scripts\\research-poc.ps1 list-bridge-runs --project {root_arg}", "Sources are missing; inspect prior bridge failures before repeating work.", "Read-only bridge state."))
    if stage_id in {"research_plan_ready", "sources_collected"}:
        commands.append(_command("Check tool health", ".\\scripts\\research-poc.ps1 get-tool-health-dashboard", "Choose a valid local bridge before running external work.", "Metadata-only; does not run downloads, fetches, or searches."))
        commands.append(
            _command(
                "Check web fetcher health",
                ".\\scripts\\research-poc.ps1 run-local-tool-action web-content-fetcher health",
                "Confirm delegated webpage fetching is available before source extraction.",
                "Allowlisted health check only; does not fetch pages.",
                tool_action={"tool_id": "web-content-fetcher", "action": "health", "args": {}},
            )
        )
    url_sources_without_fetch = _url_sources_without_fetch(project_root, sources)
    if url_sources_without_fetch:
        source = url_sources_without_fetch[0]
        commands.append(
            _command(
                "Plan fetch for source URL",
                f".\\scripts\\research-poc.ps1 plan-fetch-source-content --project {root_arg} --source-id {source.get('id', '')}",
                "At least one URL source has no fetched readable artifact.",
                "Plan only; actual fetch/import must be triggered explicitly.",
            )
        )
        commands.append(
            _command(
                "Bridge action: fetch source URL",
                f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action web_fetch_source --args-json '{{\"source_id\":\"{source.get('id', '')}\"}}'",
                "At least one URL source has no fetched readable artifact.",
                "Fetch imports readable artifacts only; source quality and evidence verification remain human-reviewed.",
                tool_action={"kind": "bridge_action", "action": "web_fetch_source", "args": {"source_id": str(source.get("id") or "")}},
            )
        )
    ai_result = _local_ai_research_result(project_root)
    if ai_result:
        commands.append(
            _command(
                "Bridge action: import local ai-research result",
                f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action ai_research_import_json --args-json '{{\"path\":\"{ai_result}\"}}'",
                "A local ai-research result JSON exists and can be imported as candidate sources/claims/evidence.",
                "Imported sources/claims/evidence remain candidates and require human review.",
                tool_action={"kind": "bridge_action", "action": "ai_research_import_json", "args": {"path": ai_result}},
            )
        )
    external_report = _local_external_researcher_report(project_root)
    if external_report:
        commands.append(
            _command(
                "Bridge action: import local external researcher report",
                f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action external_researcher_import_report --args-json '{{\"provider\":\"External researcher\",\"path\":\"{external_report}\"}}'",
                "A local external Deep Research report exists and can be imported as candidate context/source.",
                "Imported report is not verified evidence; source quality remains unknown until human review.",
                tool_action={"kind": "bridge_action", "action": "external_researcher_import_report", "args": {"provider": "External researcher", "path": external_report}},
            )
        )
    if any(item.get("item_type") in {"source_quality", "candidate_evidence", "poor_source_evidence"} for item in review_queue):
        commands.append(_command("Read review queue", f".\\scripts\\research-poc.ps1 get-review-queue --project {root_arg}", "Human review queue has items.", "Agent may summarize queue but must not auto-approve."))
    if blocking_gate == "evidence_present" or stage_id == "claims_extracted":
        commands.append(_command("Plan source fetch", f".\\scripts\\research-poc.ps1 plan-fetch-source-content --project {root_arg} --create-candidate-evidence", "Claims need evidence cards.", "Plan only unless source/claim IDs are supplied."))
        commands.append(
            _command(
                "Check web fetcher health",
                ".\\scripts\\research-poc.ps1 run-local-tool-action web-content-fetcher health",
                "Evidence gathering depends on the delegated web-content-fetcher.",
                "Allowlisted health check only; does not fetch pages.",
                tool_action={"tool_id": "web-content-fetcher", "action": "health", "args": {}},
            )
        )
    video_sources = [source for source in sources if str(source.get("source_type") or "").lower() in {"video", "video_knowledge"} or str(source.get("path") or "").lower().endswith((".mp4", ".mkv", ".mov", ".webm"))]
    if video_sources:
        commands.append(
            _command(
                "Check video knowledge pipeline",
                ".\\scripts\\research-poc.ps1 run-local-tool-action video-knowledge-pipeline asr_status",
                "Video sources need delegated ASR/frame/multimodal processing status before import.",
                "Allowlisted status check only; does not process video.",
                tool_action={"tool_id": "video-knowledge-pipeline", "action": "asr_status", "args": {}},
            )
        )
        video_path = str(video_sources[0].get("path") or video_sources[0].get("url") or "<media_path>")
        workspace = str(project_root / "video-runs" / str(video_sources[0].get("id", "video")))
        commands.append(_command("Plan video knowledge run", f".\\scripts\\research-poc.ps1 plan-video-knowledge-run {_ps_quote(video_path)} {_ps_quote(workspace)} --project {root_arg}", "Video source has not yet been imported as a video knowledge bundle.", "Read-only plan; ASR/OCR/multimodal work stays in video-knowledge-pipeline."))
        if video_path and not video_path.startswith("http") and video_path != "<media_path>":
            commands.append(
                _command(
                    "Bridge action: plan video knowledge run",
                    f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action video_plan --args-json '{{\"media_path\":\"{video_path}\",\"workspace\":\"{workspace}\"}}'",
                    "Video source has a local media path and can be turned into a delegated video run plan.",
                    "Only prepares a plan; ASR/OCR/multimodal processing stays in video-knowledge-pipeline.",
                    tool_action={"kind": "bridge_action", "action": "video_plan", "args": {"media_path": video_path, "workspace": workspace, "title": str(video_sources[0].get("title") or ""), "max_frames": 80}},
                )
            )
    bundle = _video_bundle_path(sources)
    if bundle:
        commands.append(
            _command(
                "Bridge action: check video bundle artifacts",
                f".\\scripts\\research-poc.ps1 run-bridge-action --project {root_arg} --action video_check_artifacts --args-json '{{\"bundle_dir\":\"{bundle}\"}}'",
                "A video review bundle path exists; check whether expected review and export artifacts are present.",
                "Read-only artifact check; import remains a separate explicit candidate action.",
                tool_action={"kind": "bridge_action", "action": "video_check_artifacts", "args": {"bundle_dir": bundle}},
            )
        )
    if blocking_gate == "counter_evidence_checked":
        commands.append(_command("Plan counter-evidence work", f".\\scripts\\research-poc.ps1 plan-research --project {root_arg} --add-claims", "Counter-evidence/context is missing.", "Agent-safe; generated items remain candidates."))
    if stage_id in {"evidence_reviewed", "answer_draft_ready"}:
        commands.append(_command("Draft answer", f".\\scripts\\research-poc.ps1 draft-answer --project {root_arg}", "Verified evidence exists or gates allow drafting.", "Draft is not final publication."))
        commands.append(_command("Export research pack", f".\\scripts\\research-poc.ps1 export-research-pack --project {root_arg}", "Prepare human-readable review materials.", "Review artifact only; no knowledge-base writeback."))
    if stage_id == "export_ready":
        commands.append(_command("Read research pack", f".\\scripts\\research-poc.ps1 export-research-pack --project {root_arg}", "Refresh the human-readable review pack.", "Does not publish or write to Logseq/Obsidian."))
    next_steps = _next_steps(workflow)
    for step in next_steps[:3]:
        if step.get("can_agent_execute") and not step.get("requires_human_confirmation"):
            commands.append(_command(f"Run gate step {step.get('gate_id', '')}", f".\\scripts\\research-poc.ps1 run-next-step --project {root_arg} --gate-id {step.get('gate_id', '')}", str(step.get("agent_action", "")), "Agent-safe per gate contract."))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for command in commands:
        key = command["command"]
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique[:8]


def _next_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    audit = workflow.get("gate_audit") if isinstance(workflow, dict) else {}
    next_steps_payload = workflow.get("next_steps") if isinstance(workflow, dict) else {}
    steps = audit.get("next_steps") if isinstance(audit, dict) else None
    if not steps and isinstance(next_steps_payload, dict):
        steps = next_steps_payload.get("next_steps")
    return steps if isinstance(steps, list) else []


def _human_tasks(review_queue: list[dict[str, Any]], stage: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = list(review_queue)
    if not tasks and stage.get("next_human_action"):
        tasks.append({"item_type": "stage_human_action", "title": str(stage.get("blocking_gate", "")), "action": str(stage.get("next_human_action", ""))})
    return tasks


def _safe_gap_analysis(project_root: Path) -> dict[str, Any]:
    try:
        return analyze_research_gaps(project_root, max_queries_per_round=3)
    except Exception as exc:
        return {
            "ok": False,
            "gaps": [],
            "actionable_queries": [],
            "error": str(exc),
            "human_review_required": True,
        }


def _command(title: str, command: str, why: str, boundary: str, *, tool_action: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"title": title, "command": command, "why": why, "boundary": boundary}
    if tool_action:
        row["tool_action"] = tool_action
    return row


def _url_sources_without_fetch(project_root: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fetched_dir = project_root / "fetched-sources"
    if not fetched_dir.exists():
        return [source for source in sources if str(source.get("url") or "").strip()]
    fetched_text = "\n".join(path.name for path in fetched_dir.glob("*.*"))
    rows = []
    for source in sources:
        source_id = str(source.get("id") or "")
        if str(source.get("url") or "").strip() and source_id not in fetched_text:
            rows.append(source)
    return rows


def _local_ai_research_result(project_root: Path) -> str:
    for folder in (project_root / "tool-runs", project_root / "state" / "tool-runs"):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("ai-research*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.is_file():
                return str(path)
        for path in sorted(folder.glob("*/result.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            text = path.read_text(encoding="utf-8", errors="replace")[:1000]
            if "ai-research-workflow" in text:
                return str(path)
    return ""


def _local_external_researcher_report(project_root: Path) -> str:
    for folder in (project_root / "external-researcher-inbox", project_root / "tool-runs", project_root / "state" / "tool-runs"):
        if not folder.exists():
            continue
        patterns = ("external-researcher-report*.md", "external-researcher-report*.txt", "external-researcher-report*.json", "*.external-research.md", "*.external-research.txt")
        for pattern in patterns:
            for path in sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
                if path.is_file():
                    return str(path)
        for path in sorted(folder.glob("*/result.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            text = path.read_text(encoding="utf-8", errors="replace")[:1000]
            if "external-researcher" in text or "external research" in text:
                return str(path)
    return ""


def _video_bundle_path(sources: list[dict[str, Any]]) -> str:
    for source in sources:
        source_type = str(source.get("source_type") or "").lower()
        location = str(source.get("path") or source.get("url") or "")
        if source_type in {"video_bundle", "video_knowledge"} or "webui-bundle" in location.replace("\\", "/"):
            return location
    return ""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
