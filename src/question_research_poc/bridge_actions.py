from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .ai_research_bridge import ai_research_status, import_ai_research_result, plan_ai_research_search, run_ai_research_search
from .bridge_runs import create_bridge_run, update_bridge_run
from .external_researcher_bridge import (
    answer_external_researcher_followup,
    export_external_researcher_bundle,
    import_external_researcher_report,
    plan_external_researcher_automation,
    plan_external_researcher_session,
)
from .models import now_iso
from .vane_perplexica_bridge import import_vane_perplexica_result, plan_vane_perplexica_search, run_vane_perplexica_search, vane_perplexica_status
from .video_artifact_import import import_video_knowledge_artifacts
from .video_knowledge_bridge import check_video_run_artifacts, plan_video_knowledge_run
from .web_fetch_bridge import fetch_source_content


BRIDGE_ACTION_SCHEMA = "question_research_bridge_action.v1"
ALLOWED_BRIDGE_ACTIONS = {
    "ai_research_search",
    "ai_research_import_json",
    "vane_perplexica_search",
    "vane_perplexica_import_json",
    "external_researcher_plan",
    "external_researcher_followup",
    "external_researcher_import_report",
    "external_researcher_export_bundle",
    "external_researcher_automation_plan",
    "web_fetch_source",
    "video_plan",
    "video_check_artifacts",
    "video_import_artifacts",
}


def plan_bridge_action(root: str | Path, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return run_bridge_action(root, action, args=args, execute=False)


def run_bridge_action(
    root: str | Path,
    action: str,
    *,
    args: dict[str, Any] | None = None,
    execute: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    project_root = Path(root)
    clean_action = str(action or "").strip()
    clean_args = dict(args or {})
    if clean_action not in ALLOWED_BRIDGE_ACTIONS:
        raise ValueError(f"bridge action not allowed: {clean_action}")

    validation = _validate_action(project_root, clean_action, clean_args)
    run = create_bridge_run(
        project_root,
        tool="question-research-poc",
        action=f"bridge_action:{clean_action}",
        request={"action": clean_action, "args": clean_args, "execute": bool(execute), "timeout_seconds": int(timeout_seconds)},
        command=_command_preview(project_root, clean_action, clean_args),
        status="planned" if validation["ok"] else "needs_human",
        error="" if validation["ok"] else validation["error"],
        recovery_hint=validation["recovery_hint"],
        human_review_required=not validation["ok"] or _action_needs_review(clean_action, clean_args),
        response={"validation": validation},
    )
    if not validation["ok"]:
        return _action_result(project_root, clean_action, clean_args, run, executed=False, execute=execute, result=None)
    if not execute:
        return _action_result(project_root, clean_action, clean_args, run, executed=False, execute=False, result={"plan": _plan_payload(project_root, clean_action, clean_args)})

    update_bridge_run(run, status="running")
    try:
        result = _execute_action(project_root, clean_action, clean_args, timeout_seconds=timeout_seconds)
    except Exception as exc:
        run = update_bridge_run(
            run,
            status="failed",
            error=str(exc),
            recovery_hint=_recovery_for(clean_action, str(exc)),
            human_review_required=True,
            response={"error": str(exc), "finished_at": now_iso()},
        )
        return _action_result(project_root, clean_action, clean_args, run, executed=True, execute=True, result=None)

    status = _status_from_result(clean_action, result)
    run = update_bridge_run(
        run,
        status=status,
        artifact_paths=_artifact_paths(result),
        imported_counts=_imported_counts(result),
        error=str(result.get("error") or "") if isinstance(result, dict) else "",
        recovery_hint=_recovery_from_result(clean_action, result),
        human_review_required=_human_required(clean_action, result),
        response={"result": result, "finished_at": now_iso()},
    )
    return _action_result(project_root, clean_action, clean_args, run, executed=True, execute=True, result=result)


def enqueue_bridge_actions(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    from .agent_runbook import build_agent_runbook
    from .work_queue import enqueue_task, get_work_queue

    runbook = build_agent_runbook(project_root)
    added: list[dict[str, Any]] = []
    existing_keys = {
        _task_key(task.get("tool_action"))
        for task in get_work_queue(project_root).get("tasks", [])
        if isinstance(task.get("tool_action"), dict)
    }
    for command in runbook.get("commands", []):
        tool_action = command.get("tool_action")
        if not isinstance(tool_action, dict) or tool_action.get("kind") != "bridge_action":
            continue
        key = _task_key(tool_action)
        if key in existing_keys:
            continue
        added.append(
            enqueue_task(
                project_root,
                kind="bridge_action",
                title=str(command.get("title") or tool_action.get("action") or "Bridge action"),
                command=str(command.get("command") or ""),
                human_boundary=str(command.get("boundary") or ""),
                tool_action=tool_action,
            )
        )
        existing_keys.add(key)
    queue = get_work_queue(project_root)
    return {**queue, "added": added, "added_count": len(added)}


def bridge_action_names() -> list[str]:
    return sorted(ALLOWED_BRIDGE_ACTIONS)


def _execute_action(project_root: Path, action: str, args: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    if action == "ai_research_search":
        return run_ai_research_search(
            project_root,
            query=_none(args.get("query")),
            mode=str(args.get("mode") or "auto"),
            max_results=int(args.get("max_results") or 8),
            deep=bool(args.get("deep", False)),
            no_network=bool(args.get("no_network", False)),
            fetch=bool(args.get("fetch", True)),
            import_results=bool(args.get("import_results", False)),
            base_url=_none(args.get("base_url")),
            timeout_seconds=int(args.get("timeout_seconds") or timeout_seconds),
        )
    if action == "ai_research_import_json":
        return import_ai_research_result(
            project_root,
            str(args.get("path") or args.get("result_path") or ""),
            import_sources=bool(args.get("import_sources", True)),
            import_claims=bool(args.get("import_claims", True)),
            import_evidence=bool(args.get("import_evidence", True)),
        )
    if action == "vane_perplexica_search":
        return run_vane_perplexica_search(
            project_root,
            query=_none(args.get("query")),
            sources=args.get("sources"),
            optimization_mode=str(args.get("optimization_mode") or args.get("mode") or "balanced"),
            base_url=_none(args.get("base_url")),
            chat_provider_id=str(args.get("chat_provider_id") or ""),
            chat_model_key=str(args.get("chat_model_key") or ""),
            embedding_provider_id=str(args.get("embedding_provider_id") or ""),
            embedding_model_key=str(args.get("embedding_model_key") or ""),
            system_instructions=str(args.get("system_instructions") or ""),
            import_results=bool(args.get("import_results", True)),
            timeout_seconds=int(args.get("timeout_seconds") or timeout_seconds),
        )
    if action == "vane_perplexica_import_json":
        return import_vane_perplexica_result(
            project_root,
            str(args.get("path") or args.get("result_path") or ""),
            import_sources=bool(args.get("import_sources", True)),
        )
    if action == "external_researcher_plan":
        return plan_external_researcher_session(
            project_root,
            question=_none(args.get("question")),
            clarification_answers=str(args.get("clarification_answers") or ""),
            providers=args.get("providers"),
            source_policy=str(args.get("source_policy") or ""),
            output_language=str(args.get("output_language") or "中文"),
        )
    if action == "external_researcher_followup":
        return answer_external_researcher_followup(
            project_root,
            followup_question=str(args.get("followup_question") or ""),
            manual_answer=str(args.get("manual_answer") or ""),
            original_question=_none(args.get("original_question")),
            source_policy=str(args.get("source_policy") or ""),
            auto_after_seconds=int(args.get("auto_after_seconds") or 10),
        )
    if action == "external_researcher_import_report":
        return import_external_researcher_report(
            project_root,
            provider=str(args.get("provider") or "External researcher"),
            report_text=_report_text_arg(args),
            prompt_text=str(args.get("prompt_text") or ""),
            report_url=str(args.get("report_url") or ""),
            notes=_report_notes_arg(args),
            import_as_source=bool(args.get("import_as_source", True)),
        )
    if action == "external_researcher_export_bundle":
        return export_external_researcher_bundle(project_root, output_dir=_none(args.get("output_dir")))
    if action == "external_researcher_automation_plan":
        return plan_external_researcher_automation(
            project_root,
            question=_none(args.get("question")),
            clarification_answers=str(args.get("clarification_answers") or ""),
            providers=args.get("providers"),
            source_policy=str(args.get("source_policy") or ""),
            output_language=str(args.get("output_language") or "中文"),
            profile_config_path=str(args.get("profile_config_path") or ""),
            followup_wait_seconds=int(args.get("followup_wait_seconds") or 10),
            max_wait_seconds=int(args.get("max_wait_seconds") or 900),
        )
    if action == "web_fetch_source":
        return fetch_source_content(
            project_root,
            source_id=_none(args.get("source_id")),
            url=_none(args.get("url")),
            title=_none(args.get("title")),
            claim_id=_none(args.get("claim_id")),
            fetch_profile=str(args.get("fetch_profile") or "generic"),
            backend=str(args.get("backend") or "auto"),
            extractor=str(args.get("extractor") or "auto"),
            use_browser=bool(args.get("use_browser", False)),
            include_raw=bool(args.get("include_raw", False)),
            timeout_seconds=int(args.get("timeout_seconds") or 30),
            import_source=bool(args.get("import_source", True)),
            create_candidate_evidence=bool(args.get("create_candidate_evidence", False)),
        )
    if action == "video_plan":
        return plan_video_knowledge_run(
            str(args.get("media_path") or ""),
            str(args.get("workspace") or ""),
            title=str(args.get("title") or ""),
            max_frames=int(args.get("max_frames") or 80),
            build_initial_bundle=bool(args.get("build_initial_bundle", True)),
            root=_none(args.get("root") or args.get("video_knowledge_root")),
            project_root=project_root,
        )
    if action == "video_check_artifacts":
        return check_video_run_artifacts(str(args.get("bundle_dir") or ""))
    if action == "video_import_artifacts":
        return import_video_knowledge_artifacts(
            project_root,
            str(args.get("bundle_dir") or ""),
            title=str(args.get("title") or ""),
            claim_id=str(args.get("claim_id") or ""),
            source_quality=str(args.get("source_quality") or "unknown"),
        )
    raise ValueError(f"bridge action not implemented: {action}")


def _validate_action(project_root: Path, action: str, args: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    if action == "ai_research_import_json" and not (args.get("path") or args.get("result_path")):
        missing.append("path")
    if action == "vane_perplexica_import_json" and not (args.get("path") or args.get("result_path")):
        missing.append("path")
    if action == "external_researcher_followup" and not args.get("followup_question"):
        missing.append("followup_question")
    if action == "external_researcher_import_report":
        if not args.get("provider"):
            missing.append("provider")
        if not (args.get("report_text") or args.get("path") or args.get("report_path")):
            missing.append("report_text_or_path")
    if action == "web_fetch_source":
        if not (args.get("source_id") or args.get("url")):
            missing.append("source_id_or_url")
        if bool(args.get("create_candidate_evidence")) and not args.get("claim_id"):
            missing.append("claim_id")
    if action == "video_plan":
        if not args.get("media_path"):
            missing.append("media_path")
        if not args.get("workspace"):
            missing.append("workspace")
    if action in {"video_check_artifacts", "video_import_artifacts"} and not args.get("bundle_dir"):
        missing.append("bundle_dir")
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "error": f"missing required bridge action argument(s): {', '.join(missing)}",
            "recovery_hint": "补齐关键参数后再执行；队列不会用不完整参数调用外部桥接工具。",
        }
    backend = _validate_backend(project_root, action, args)
    if not backend["ok"]:
        return backend
    return {"ok": True, "missing": [], "error": "", "recovery_hint": ""}


def _validate_backend(project_root: Path, action: str, args: dict[str, Any]) -> dict[str, Any]:
    if action == "ai_research_search":
        status = ai_research_status(args.get("base_url"), timeout_seconds=2)
        if not status.get("ok"):
            return {
                "ok": False,
                "missing": [],
                "blocked_by_backend": "ai-research-workflow",
                "backend_status": status,
                "error": "ai-research-workflow is unreachable; bridge action did not run.",
                "recovery_hint": status.get("next_action") or "启动 ai-research-workflow HTTP 服务后重试；不要静默改走手工搜索。",
            }
    if action == "vane_perplexica_search":
        status = vane_perplexica_status(args.get("base_url"))
        if not status.get("ok"):
            return {
                "ok": False,
                "missing": [],
                "blocked_by_backend": "vane-perplexica",
                "backend_status": status,
                "error": "Vane/Perplexica service is unreachable; bridge action did not run.",
                "recovery_hint": status.get("recovery_hint") or "启动 Vane/Perplexica 后端或导入本地 result JSON；只导入 candidate sources。",
            }
    return {"ok": True}


def _plan_payload(project_root: Path, action: str, args: dict[str, Any]) -> dict[str, Any]:
    if action == "ai_research_search":
        return plan_ai_research_search(
            project_root,
            query=_none(args.get("query")),
            mode=str(args.get("mode") or "auto"),
            max_results=int(args.get("max_results") or 8),
            deep=bool(args.get("deep", False)),
            no_network=bool(args.get("no_network", False)),
            fetch=bool(args.get("fetch", True)),
            import_results=bool(args.get("import_results", False)),
            base_url=_none(args.get("base_url")),
        )
    if action == "vane_perplexica_search":
        return plan_vane_perplexica_search(
            project_root,
            query=_none(args.get("query")),
            sources=args.get("sources"),
            optimization_mode=str(args.get("optimization_mode") or args.get("mode") or "balanced"),
            base_url=_none(args.get("base_url")),
            chat_provider_id=str(args.get("chat_provider_id") or ""),
            chat_model_key=str(args.get("chat_model_key") or ""),
            embedding_provider_id=str(args.get("embedding_provider_id") or ""),
            embedding_model_key=str(args.get("embedding_model_key") or ""),
            system_instructions=str(args.get("system_instructions") or ""),
            import_results=bool(args.get("import_results", True)),
        )
    if action == "external_researcher_plan":
        return plan_external_researcher_session(
            project_root,
            question=_none(args.get("question")),
            clarification_answers=str(args.get("clarification_answers") or ""),
            providers=args.get("providers"),
            source_policy=str(args.get("source_policy") or ""),
            output_language=str(args.get("output_language") or "中文"),
        )
    if action == "external_researcher_automation_plan":
        return plan_external_researcher_automation(
            project_root,
            question=_none(args.get("question")),
            clarification_answers=str(args.get("clarification_answers") or ""),
            providers=args.get("providers"),
            source_policy=str(args.get("source_policy") or ""),
            output_language=str(args.get("output_language") or "中文"),
            profile_config_path=str(args.get("profile_config_path") or ""),
            followup_wait_seconds=int(args.get("followup_wait_seconds") or 10),
            max_wait_seconds=int(args.get("max_wait_seconds") or 900),
        )
    return {"action": action, "args": args, "command": _command_preview(project_root, action, args)}


def _command_preview(project_root: Path, action: str, args: dict[str, Any]) -> str:
    return f".\\scripts\\research-poc.ps1 run-bridge-action --project '{str(project_root)}' --action {action} --args-json '<json>' --execute"


def _action_result(project_root: Path, action: str, args: dict[str, Any], run: dict[str, Any], *, executed: bool, execute: bool, result: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": bool(run.get("ok")),
        "schema": BRIDGE_ACTION_SCHEMA,
        "root": str(project_root),
        "action": action,
        "args": args,
        "status": run.get("status"),
        "executed": executed,
        "dry_run": not execute,
        "bridge_run": run,
        "bridge_run_id": run.get("id", ""),
        "bridge_run_path": run.get("path", ""),
        "artifact_paths": run.get("artifact_paths", []),
        "imported_counts": run.get("imported_counts", {}),
        "error": run.get("error", ""),
        "recovery_hint": run.get("recovery_hint", ""),
        "blocked_by_backend": _blocked_by_backend(run),
        "human_review_required": bool(run.get("human_review_required")),
        "result": result,
    }


def _blocked_by_backend(run: dict[str, Any]) -> str:
    response = run.get("response") if isinstance(run.get("response"), dict) else {}
    validation = response.get("validation") if isinstance(response.get("validation"), dict) else {}
    return str(validation.get("blocked_by_backend") or "")


def _status_from_result(action: str, result: dict[str, Any]) -> str:
    if not bool(result.get("ok", True)):
        return "failed"
    if action in {"ai_research_import_json", "vane_perplexica_import_json", "external_researcher_import_report", "video_import_artifacts"}:
        return "imported"
    if action == "vane_perplexica_search" and result.get("imported"):
        return "imported"
    if action == "ai_research_search" and result.get("imported"):
        return "imported"
    if action == "web_fetch_source" and (result.get("candidate_evidence") or result.get("source")):
        return "imported"
    return "succeeded"


def _artifact_paths(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("run_path", "json_path", "markdown_path", "import_path", "manifest_path", "note_path"):
        if result.get(key):
            paths.append(str(result[key]))
    bridge_run = result.get("bridge_run")
    if isinstance(bridge_run, dict):
        paths.extend(str(value) for value in bridge_run.get("artifact_paths", []) if value)
        if bridge_run.get("path"):
            paths.append(str(bridge_run["path"]))
    expected = result.get("expected_artifacts")
    if isinstance(expected, dict):
        paths.extend(str(value) for value in expected.values() if value)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        for value in artifacts.values():
            if isinstance(value, dict) and value.get("path"):
                paths.append(str(value["path"]))
    return sorted(set(paths))


def _imported_counts(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("counts"), dict):
        return result["counts"]
    bridge_run = result.get("bridge_run")
    if isinstance(bridge_run, dict) and isinstance(bridge_run.get("imported_counts"), dict):
        return bridge_run["imported_counts"]
    if result.get("candidate_evidence") is not None:
        return {"sources": 1 if result.get("source") else 0, "evidence": len(result.get("candidate_evidence") or [])}
    if result.get("source"):
        return {"sources": 1, "evidence": 1 if result.get("evidence") else 0}
    return {}


def _human_required(action: str, result: dict[str, Any]) -> bool:
    if bool(result.get("human_review_required")):
        return True
    bridge_run = result.get("bridge_run")
    if isinstance(bridge_run, dict) and bridge_run.get("human_review_required"):
        return True
    return action in {"ai_research_import_json", "vane_perplexica_import_json", "external_researcher_import_report", "external_researcher_export_bundle", "web_fetch_source", "video_import_artifacts"} or action.startswith("external_researcher")


def _action_needs_review(action: str, args: dict[str, Any]) -> bool:
    return action in {"ai_research_import_json", "vane_perplexica_import_json", "external_researcher_import_report", "external_researcher_export_bundle", "web_fetch_source", "video_import_artifacts"} or action.startswith("external_researcher") or bool(args.get("import_results"))


def _recovery_from_result(action: str, result: dict[str, Any]) -> str:
    if result.get("failure_next_action"):
        return str(result["failure_next_action"])
    if result.get("next_actions"):
        return "；".join(str(item) for item in result["next_actions"])
    bridge_run = result.get("bridge_run")
    if isinstance(bridge_run, dict) and bridge_run.get("recovery_hint"):
        return str(bridge_run["recovery_hint"])
    return _recovery_for(action, "")


def _recovery_for(action: str, error: str) -> str:
    if action.startswith("ai_research"):
        return "检查 ai-research-workflow 服务、base_url/端口和 result JSON；导入内容仍保持 candidate。"
    if action.startswith("vane_perplexica"):
        return "检查 Vane/Perplexica 服务、/api/providers、provider/model 配置和 /api/search；只导入 candidate sources。"
    if action.startswith("external_researcher"):
        return "检查外部研究报告输入、provider/profile 配置和人工授权边界；导入内容只作为 candidate context/source。"
    if action == "web_fetch_source":
        return "检查 source_id/url、web-content-fetcher 本地工具、网络/浏览器抓取配置；不会自动标来源质量。"
    if action.startswith("video"):
        return "检查本地视频路径或 bundle artifacts；视频知识包导入后仍需人工审核。"
    return str(error or "检查 bridge action 参数后重试。")


def _task_key(tool_action: Any) -> str:
    if not isinstance(tool_action, dict):
        return ""
    return f"{tool_action.get('kind')}:{tool_action.get('action')}:{tool_action.get('args')}"


def _none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _report_text_arg(args: dict[str, Any]) -> str:
    if args.get("report_text"):
        return str(args["report_text"])
    path_value = str(args.get("path") or args.get("report_path") or "")
    if not path_value:
        return ""
    return Path(path_value).read_text(encoding="utf-8", errors="replace")


def _report_notes_arg(args: dict[str, Any]) -> str:
    notes = str(args.get("notes") or "").strip()
    path_value = str(args.get("path") or args.get("report_path") or "").strip()
    if path_value:
        path_note = f"Imported from local external researcher report path: {path_value}"
        return f"{notes} {path_note}".strip()
    return notes
