from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bridge_runs import create_bridge_run
from .external_researcher_bridge import (
    export_external_researcher_bundle,
    plan_external_researcher_automation,
    run_external_researcher_automation,
)
from .models import new_id, now_iso
from .storage import ensure_project_dirs, write_json


OMNIGENT_POC_SCHEMA = "question_research_omnigent_poc.v1"


def run_omnigent_external_research_poc(
    root: str | Path,
    *,
    question: str | None = None,
    clarification_answers: str = "",
    providers: str | list[str] | None = None,
    source_policy: str = "",
    output_language: str = "中文",
    profile_config_path: str = "",
    followup_wait_seconds: int = 10,
    max_wait_seconds: int = 900,
    headless: bool = False,
    import_as_source: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Run the smallest Omnigent-style wrapper around the existing external researcher bridge."""
    project_root = Path(root)
    paths = ensure_project_dirs(project_root)
    run_dir = paths["root"] / "tool-runs" / f"omnigent-external-research-poc-{now_iso().replace(':', '-')}-{new_id('run').removeprefix('run_')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    automation_plan = plan_external_researcher_automation(
        project_root,
        question=question,
        clarification_answers=clarification_answers,
        providers=providers,
        source_policy=source_policy,
        output_language=output_language,
        profile_config_path=profile_config_path,
        followup_wait_seconds=followup_wait_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    agent_spec = _agent_spec_payload(
        automation_plan,
        profile_config_path=profile_config_path,
        followup_wait_seconds=followup_wait_seconds,
        max_wait_seconds=max_wait_seconds,
        dry_run=dry_run,
    )
    spec_path = run_dir / "agent_spec.yaml"
    spec_path.write_text(_render_agent_spec_yaml(agent_spec), encoding="utf-8")

    inbox_events = _initial_inbox_events(automation_plan, spec_path=spec_path, dry_run=dry_run)
    inbox_path = run_dir / "research_inbox.jsonl"
    _write_jsonl(inbox_path, inbox_events)

    automation_run = run_external_researcher_automation(
        project_root,
        automation_plan=automation_plan["json_path"],
        followup_wait_seconds=followup_wait_seconds,
        max_wait_seconds=max_wait_seconds,
        headless=headless,
        import_as_source=import_as_source,
        dry_run=dry_run,
    )
    run_event = {
        "schema": OMNIGENT_POC_SCHEMA,
        "kind": "automation_run_finished",
        "created_at": now_iso(),
        "dry_run": bool(dry_run),
        "status": "planned" if dry_run else _automation_status(automation_run),
        "bridge_run_id": _bridge_run_id(automation_run),
        "human_review_required": True,
    }
    inbox_events.append(run_event)
    _write_jsonl(inbox_path, inbox_events)

    bundle = export_external_researcher_bundle(project_root)
    summary = {
        "schema": OMNIGENT_POC_SCHEMA,
        "kind": "external_research_orchestration",
        "ok": True,
        "root": str(project_root),
        "dry_run": bool(dry_run),
        "question": automation_plan.get("question", ""),
        "providers": automation_plan.get("providers", []),
        "agent_spec_path": str(spec_path),
        "inbox_path": str(inbox_path),
        "automation_plan_path": automation_plan.get("json_path", ""),
        "automation_plan_markdown_path": automation_plan.get("markdown_path", ""),
        "automation_run": automation_run,
        "aggregate_markdown_path": bundle.get("markdown_path", ""),
        "aggregate_json_path": bundle.get("json_path", ""),
        "report_count": int(bundle.get("report_count") or 0),
        "followup_policy": {
            "human_wait_seconds": int(followup_wait_seconds),
            "fallback": automation_plan.get("followup_default_answer", ""),
            "source": "existing external_researcher_automation followup marker handler",
        },
        "candidate_only_boundary": [
            "Provider deep research reports are candidate context only.",
            "This PoC does not promote claims or evidence.",
            "Sources, claims, and sentence-level provenance still require the normal review gates.",
        ],
        "created_at": now_iso(),
    }
    json_path = run_dir / "run.json"
    markdown_path = run_dir / "run.md"
    write_json(json_path, summary)
    markdown_path.write_text(_render_run_markdown(summary, agent_spec), encoding="utf-8")

    status = "planned" if dry_run else _bridge_status(automation_run)
    bridge_run = create_bridge_run(
        project_root,
        tool="omnigent-poc",
        action="run_omnigent_external_research_poc",
        request={
            "question": automation_plan.get("question", ""),
            "providers": automation_plan.get("providers", []),
            "dry_run": bool(dry_run),
            "profile_config_path": profile_config_path,
        },
        command="run Omnigent-style external researcher PoC",
        status=status,
        artifact_paths=[
            str(spec_path),
            str(inbox_path),
            str(json_path),
            str(markdown_path),
            str(automation_plan.get("json_path", "")),
            str(automation_plan.get("markdown_path", "")),
            str(bundle.get("markdown_path", "")),
        ],
        imported_counts={"sources": int(bundle.get("report_count") or 0), "claims": 0, "evidence": 0},
        human_review_required=True,
        response={"dry_run": bool(dry_run), "agent_spec_path": str(spec_path), "inbox_path": str(inbox_path)},
    )
    return {
        **summary,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "bridge_run": bridge_run,
        "human_review_required": True,
    }


def _agent_spec_payload(
    automation_plan: dict[str, Any],
    *,
    profile_config_path: str,
    followup_wait_seconds: int,
    max_wait_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    providers = automation_plan.get("providers", [])
    return {
        "spec_version": "omnigent-style.v1",
        "name": "external_deep_research_orchestrator",
        "description": "Question clarification, delegated web deep research workers, follow-up inbox, and Markdown aggregation.",
        "model": "local-controller",
        "instructions": [
            "Clarify the research question before dispatch.",
            "Delegate each provider to the existing external researcher browser automation adapter.",
            "If a provider asks a follow-up, emit a visible inbox event and wait for human input before using the default answer.",
            "Export all collected reports to one Markdown bundle; keep them candidate-only.",
        ],
        "tools": [
            "plan_external_researcher_automation",
            "run_external_researcher_automation",
            "answer_external_researcher_followup",
            "export_external_researcher_bundle",
            "sys_read_inbox",
            "sys_write_inbox",
            "elicitation",
        ],
        "workers": [
            {
                "name": _worker_name(provider),
                "role": "external_deep_research_provider",
                "provider": provider,
                "executor": "run_external_researcher_automation",
                "async_inbox": "research_inbox.jsonl",
            }
            for provider in providers
        ],
        "policy": {
            "followup_wait_seconds": int(followup_wait_seconds),
            "max_wait_seconds": int(max_wait_seconds),
            "dry_run": bool(dry_run),
            "profile_config_path": profile_config_path,
            "candidate_only": True,
            "no_login_or_captcha_bypass": True,
        },
    }


def _initial_inbox_events(automation_plan: dict[str, Any], *, spec_path: Path, dry_run: bool) -> list[dict[str, Any]]:
    now = now_iso()
    events: list[dict[str, Any]] = [
        {
            "schema": OMNIGENT_POC_SCHEMA,
            "kind": "clarification_completed",
            "created_at": now,
            "question": automation_plan.get("question", ""),
            "clarification_answers": automation_plan.get("clarification_answers", ""),
        },
        {
            "schema": OMNIGENT_POC_SCHEMA,
            "kind": "agent_spec_created",
            "created_at": now,
            "path": str(spec_path),
        },
    ]
    for provider in automation_plan.get("providers", []):
        events.append(
            {
                "schema": OMNIGENT_POC_SCHEMA,
                "kind": "provider_worker_dispatched" if not dry_run else "provider_worker_planned",
                "created_at": now,
                "provider": provider,
                "worker": _worker_name(provider),
                "inbox_topics": ["provider_followup", "provider_report_ready", "provider_needs_human"],
            }
        )
    events.append(
        {
            "schema": OMNIGENT_POC_SCHEMA,
            "kind": "human_followup_gate_ready",
            "created_at": now,
            "wait_seconds": int(automation_plan.get("followup_wait_seconds") or 10),
            "fallback": automation_plan.get("followup_default_answer", ""),
        }
    )
    return events


def _render_agent_spec_yaml(spec: dict[str, Any]) -> str:
    lines = [
        f"spec_version: {spec['spec_version']}",
        f"name: {spec['name']}",
        f"description: {_yaml_string(spec['description'])}",
        f"model: {spec['model']}",
        "instructions:",
    ]
    lines.extend(f"  - {_yaml_string(item)}" for item in spec["instructions"])
    lines.append("tools:")
    lines.extend(f"  - {tool}" for tool in spec["tools"])
    lines.append("workers:")
    for worker in spec["workers"]:
        lines.extend(
            [
                f"  - name: {worker['name']}",
                f"    role: {worker['role']}",
                f"    provider: {_yaml_string(worker['provider'])}",
                f"    executor: {worker['executor']}",
                f"    async_inbox: {worker['async_inbox']}",
            ]
        )
    lines.append("policy:")
    for key, value in spec["policy"].items():
        lines.append(f"  {key}: {_yaml_scalar(value)}")
    lines.append("")
    return "\n".join(lines)


def _render_run_markdown(summary: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# Omnigent-Style External Research PoC",
        "",
        "## Flow",
        "",
        "- Question clarification is captured before dispatch.",
        "- Existing external researcher automation is the provider executor.",
        "- Provider follow-ups use a visible inbox gate, then a default answer after the timeout.",
        "- Provider reports are exported into one Markdown bundle.",
        "",
        "## Artifacts",
        "",
        f"- Agent spec: `{summary['agent_spec_path']}`",
        f"- Inbox: `{summary['inbox_path']}`",
        f"- Automation plan: `{summary['automation_plan_path']}`",
        f"- Aggregate Markdown: `{summary['aggregate_markdown_path']}`",
        "",
        "## Workers",
        "",
    ]
    for worker in spec["workers"]:
        lines.append(f"- `{worker['name']}`: {worker['provider']}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This PoC keeps all external provider output as candidate context.",
            "- Claims, evidence, and sentence-level source tracking are not promoted here.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _worker_name(provider: Any) -> str:
    text = str(provider or "external").strip().lower()
    slug = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in text).strip("_")
    return f"researcher_{slug or 'external'}"


def _automation_status(result: dict[str, Any]) -> str:
    bridge_run = result.get("bridge_run")
    if isinstance(bridge_run, dict):
        return str(bridge_run.get("status") or "")
    return "succeeded" if result.get("ok") else "failed"


def _bridge_status(result: dict[str, Any]) -> str:
    status = _automation_status(result)
    if status in {"succeeded", "failed", "needs_human"}:
        return status
    return "succeeded" if result.get("ok") else "failed"


def _bridge_run_id(result: dict[str, Any]) -> str:
    bridge_run = result.get("bridge_run")
    if isinstance(bridge_run, dict):
        return str(bridge_run.get("id") or "")
    return ""


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return _yaml_string(str(value))


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
