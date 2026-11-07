from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .bridge_runs import create_bridge_run
from .external_researcher_automation import build_provider_profiles, open_provider_login_profiles, preflight_provider_profile, render_profile_config_template, run_provider_browser_automation
from .models import dataclass_to_dict, now_iso
from .orchestrator import add_source, list_records
from .storage import ensure_project_dirs, load_project, write_json


EXTERNAL_RESEARCHER_SCHEMA = "question_research_external_researcher.v1"
DEFAULT_PROVIDERS = [
    "豆包深入研究",
    "通义千问研究",
]


def plan_external_researcher_session(
    root: str | Path,
    *,
    question: str | None = None,
    clarification_answers: str = "",
    providers: str | list[str] | None = None,
    source_policy: str = "",
    output_language: str = "中文",
) -> dict[str, Any]:
    project = load_project(root)
    resolved_question = str(question or project.question).strip()
    provider_list = _provider_list(providers)
    prompt = _render_deep_research_prompt(
        resolved_question,
        clarification_answers=clarification_answers,
        source_policy=source_policy,
        output_language=output_language,
    )
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "plan",
        "question": resolved_question,
        "providers": provider_list,
        "clarification_questions": _clarification_questions(resolved_question),
        "clarification_answers": clarification_answers,
        "source_policy": source_policy,
        "output_language": output_language,
        "deep_research_prompt": prompt,
        "followup_default_answer": default_followup_answer(resolved_question, source_policy=source_policy),
        "operator_boundary": [
            "This bridge does not automate third-party web UIs.",
            "Copy the generated prompt into each provider's deep research mode manually or through a future provider adapter.",
            "Provider answers are candidate context only until sources and evidence are reviewed in question-research-poc.",
        ],
    }
    paths = _write_external_artifacts(root, "external-researcher-plan", payload, markdown=_render_plan_markdown(payload))
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="plan_external_researcher_session",
        request={"question": resolved_question, "providers": provider_list},
        command="manual web deep-research prompt copy",
        status="needs_human",
        artifact_paths=[paths["json_path"], paths["markdown_path"]],
        human_review_required=True,
        response={"prompt_path": paths["markdown_path"], "providers": provider_list},
    )
    return {"ok": True, **payload, **paths, "bridge_run": bridge_run}


def answer_external_researcher_followup(
    root: str | Path,
    *,
    followup_question: str,
    manual_answer: str = "",
    original_question: str | None = None,
    source_policy: str = "",
    auto_after_seconds: int = 10,
) -> dict[str, Any]:
    project = load_project(root)
    resolved_question = str(original_question or project.question).strip()
    clean_followup = str(followup_question or "").strip()
    clean_manual = str(manual_answer or "").strip()
    answer_source = "manual" if clean_manual else "auto_default"
    answer = clean_manual or default_followup_answer(resolved_question, source_policy=source_policy)
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "followup_answer",
        "question": resolved_question,
        "followup_question": clean_followup,
        "answer": answer,
        "answer_source": answer_source,
        "auto_after_seconds": int(auto_after_seconds),
        "created_at": now_iso(),
        "operator_boundary": "If no human answer is supplied before the timeout, use the conservative default answer and keep assumptions visible in the provider report.",
    }
    paths = _write_external_artifacts(root, "external-researcher-followup", payload, markdown=_render_followup_markdown(payload))
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="answer_external_researcher_followup",
        request={"followup_question": clean_followup, "answer_source": answer_source},
        command="manual follow-up intervention or auto-default",
        status="succeeded",
        artifact_paths=[paths["json_path"], paths["markdown_path"]],
        human_review_required=answer_source != "manual",
        response={"answer_source": answer_source, "answer": answer},
    )
    return {"ok": True, **payload, **paths, "bridge_run": bridge_run}


def import_external_researcher_report(
    root: str | Path,
    *,
    provider: str,
    report_text: str,
    prompt_text: str = "",
    report_url: str = "",
    notes: str = "",
    import_as_source: bool = True,
) -> dict[str, Any]:
    clean_provider = str(provider or "External researcher").strip()
    clean_report = str(report_text or "").strip()
    if not clean_report:
        raise ValueError("report_text is required")
    project_identity = _current_project_identity(root)
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "provider_report",
        **project_identity,
        "provider": clean_provider,
        "report_url": str(report_url or "").strip(),
        "prompt_text": str(prompt_text or "").strip(),
        "report_text": clean_report,
        "notes": str(notes or "").strip(),
        "candidate": True,
        "created_at": now_iso(),
        "boundary": "Imported provider report is candidate context only. Source quality and sentence-level evidence remain unverified.",
    }
    paths = _write_external_artifacts(root, "external-researcher-report", payload, markdown=_render_report_markdown(payload))
    imported_source = None
    if import_as_source:
        imported_source = add_source(
            root,
            title=f"{clean_provider} external research report",
            url=payload["report_url"],
            path=paths["markdown_path"],
            source_type="external_research_report",
            quality="unknown",
            notes=(
                "Candidate report imported from a third-party web deep research UI. "
                "Use as context only; verify source links and evidence separately. "
                f"Raw report artifact: {paths['json_path']}"
            ),
        )
    counts = {"sources": 1 if imported_source else 0, "claims": 0, "evidence": 0}
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="import_external_researcher_report",
        request={"provider": clean_provider, "report_url": payload["report_url"], "import_as_source": import_as_source},
        command="manual provider report paste",
        status="imported" if imported_source else "succeeded",
        artifact_paths=[paths["json_path"], paths["markdown_path"]],
        imported_counts=counts,
        human_review_required=True,
        response={"provider": clean_provider, "candidate": True, "source": dataclass_to_dict(imported_source) if imported_source else None},
    )
    return {
        "ok": True,
        **payload,
        **paths,
        "source": dataclass_to_dict(imported_source) if imported_source else None,
        "counts": counts,
        "bridge_run": bridge_run,
    }


def save_external_researcher_report_draft(
    root: str | Path,
    *,
    provider: str,
    report_text: str,
    prompt_text: str = "",
    report_url: str = "",
    notes: str = "",
) -> dict[str, Any]:
    clean_provider = str(provider or "External researcher").strip()
    clean_report = str(report_text or "").strip()
    if not clean_report:
        raise ValueError("report_text is required")
    project_identity = _current_project_identity(root)
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "provider_report_draft",
        **project_identity,
        "provider": clean_provider,
        "report_url": str(report_url or "").strip(),
        "prompt_text": str(prompt_text or "").strip(),
        "report_text": clean_report,
        "notes": str(notes or "").strip(),
        "candidate": True,
        "draft": True,
        "created_at": now_iso(),
        "boundary": "Autosaved provider report draft. It is candidate context only until reviewed.",
    }
    paths = ensure_project_dirs(root)
    draft_dir = paths["root"] / "drafts" / "external-researcher"
    draft_dir.mkdir(parents=True, exist_ok=True)
    slug = _provider_slug(clean_provider)
    json_path = draft_dir / f"{slug}.json"
    markdown_path = draft_dir / f"{slug}.md"
    write_json(json_path, payload)
    markdown_path.write_text(_render_report_markdown(payload), encoding="utf-8")
    return {"ok": True, **payload, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def export_external_researcher_bundle(root: str | Path, *, output_dir: str | Path | None = None) -> dict[str, Any]:
    reports = list_external_researcher_reports(root)["reports"]
    paths = ensure_project_dirs(root)
    out_dir = Path(output_dir) if output_dir else paths["root"] / "exports" / "external-researcher"
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = out_dir / "external-researcher-aggregate.md"
    json_path = out_dir / "external-researcher-aggregate.json"
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "aggregate",
        "created_at": now_iso(),
        "report_count": len(reports),
        "reports": reports,
        "candidate": True,
        "boundary": "This aggregate collects external web deep-research reports. It is not sentence-level verified evidence.",
    }
    write_json(json_path, payload)
    markdown_path.write_text(_render_aggregate_markdown(root, payload), encoding="utf-8")
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="export_external_researcher_bundle",
        request={"output_dir": str(out_dir)},
        command="export external researcher aggregate markdown",
        status="succeeded",
        artifact_paths=[str(markdown_path), str(json_path)],
        human_review_required=True,
        response={"report_count": len(reports), "markdown_path": str(markdown_path)},
    )
    return {"ok": True, "output_dir": str(out_dir), "markdown_path": str(markdown_path), "json_path": str(json_path), "report_count": len(reports), "bridge_run": bridge_run}


def plan_external_researcher_automation(
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
) -> dict[str, Any]:
    plan = plan_external_researcher_session(
        root,
        question=question,
        clarification_answers=clarification_answers,
        providers=providers,
        source_policy=source_policy,
        output_language=output_language,
    )
    provider_profiles = build_provider_profiles(plan["providers"], root=root, profile_config_path=profile_config_path or None)
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "automation_plan",
        "created_at": now_iso(),
        "question": plan["question"],
        "providers": plan["providers"],
        "deep_research_prompt": plan["deep_research_prompt"],
        "followup_default_answer": plan["followup_default_answer"],
        "profile_config_path": profile_config_path,
        "persistent_profile_root": _profile_root_from_profiles(provider_profiles),
        "followup_wait_seconds": int(followup_wait_seconds),
        "max_wait_seconds": int(max_wait_seconds),
        "provider_profiles": provider_profiles,
        "run_command": "research-poc run-external-researcher-automation --project <project> --automation-plan <json_path>",
        "operator_boundary": [
            "Browser automation may click and type only in logged-in, authorized web sessions.",
            "Provider login state is persisted in the configured user_data_dir for each provider profile.",
            "Login, CAPTCHA, payment walls, and provider policy restrictions remain human-only.",
            "If a provider asks a follow-up, the runner waits for human intervention and then submits the default answer after the timeout.",
            "Collected provider reports are still candidate context, not verified evidence.",
        ],
    }
    paths = _write_external_artifacts(root, "external-researcher-automation-plan", payload, markdown=_render_automation_plan_markdown(payload))
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="plan_external_researcher_automation",
        request={"providers": plan["providers"], "profile_config_path": profile_config_path},
        command=payload["run_command"].replace("<project>", str(root)).replace("<json_path>", paths["json_path"]),
        status="planned",
        artifact_paths=[paths["json_path"], paths["markdown_path"]],
        human_review_required=True,
        response={"provider_count": len(provider_profiles), "json_path": paths["json_path"]},
    )
    return {"ok": True, **payload, **paths, "bridge_run": bridge_run}


def _profile_root_from_profiles(provider_profiles: list[dict[str, Any]]) -> str:
    dirs = [Path(str(profile.get("user_data_dir") or "")).parent for profile in provider_profiles if profile.get("user_data_dir")]
    if not dirs:
        return ""
    first = dirs[0]
    return str(first)


def run_external_researcher_automation(
    root: str | Path,
    *,
    automation_plan: str | Path = "",
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
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = _load_or_create_automation_plan(
        root,
        automation_plan=automation_plan,
        question=question,
        clarification_answers=clarification_answers,
        providers=providers,
        source_policy=source_policy,
        output_language=output_language,
        profile_config_path=profile_config_path,
        followup_wait_seconds=followup_wait_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    if dry_run:
        bridge_run = create_bridge_run(
            root,
            tool="external-researcher",
            action="run_external_researcher_automation",
            request={"automation_plan": plan.get("json_path", ""), "dry_run": True},
            command="dry-run browser automation",
            status="planned",
            artifact_paths=[str(plan.get("json_path", "")), str(plan.get("markdown_path", ""))],
            human_review_required=True,
            response={"providers": plan.get("providers", []), "dry_run": True},
        )
        return {"ok": True, "dry_run": True, "plan": plan, "bridge_run": bridge_run}

    results: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    for profile in plan.get("provider_profiles", []):
        if not profile.get("enabled", True):
            results.append({"provider": profile.get("provider"), "status": "skipped", "error": "profile disabled"})
            continue
        result = run_provider_browser_automation(
            profile,
            prompt=str(plan.get("deep_research_prompt") or ""),
            default_followup_answer=str(plan.get("followup_default_answer") or default_followup_answer(str(plan.get("question") or ""), source_policy=source_policy)),
            followup_wait_seconds=int(plan.get("followup_wait_seconds") or followup_wait_seconds),
            max_wait_seconds=int(plan.get("max_wait_seconds") or max_wait_seconds),
            headless=headless,
        )
        results.append(result)
        report_text = str(result.get("report_text") or "").strip()
        if report_text:
            imported.append(
                import_external_researcher_report(
                    root,
                    provider=str(result.get("provider") or "External researcher"),
                    report_text=report_text,
                    prompt_text=str(plan.get("deep_research_prompt") or ""),
                    report_url=str(result.get("url") or ""),
                    notes=f"Imported from browser automation. status={result.get('status')}; followup={json.dumps(result.get('followup') or {}, ensure_ascii=False)}",
                    import_as_source=import_as_source,
                )
            )
    status = "succeeded" if results and all(row.get("status") == "succeeded" for row in results) else "needs_human"
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "automation_run",
        "created_at": now_iso(),
        "question": plan.get("question", ""),
        "plan_path": plan.get("json_path", str(automation_plan or "")),
        "results": results,
        "imported_count": len(imported),
        "boundary": "Browser automation collected external reports as candidate context only.",
    }
    paths = _write_external_artifacts(root, "external-researcher-automation-run", payload, markdown=_render_automation_run_markdown(payload))
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="run_external_researcher_automation",
        request={"automation_plan": payload["plan_path"], "headless": headless, "import_as_source": import_as_source},
        command="playwright browser automation for web deep research providers",
        status=status,
        artifact_paths=[paths["json_path"], paths["markdown_path"], *[item["markdown_path"] for item in imported if item.get("markdown_path")]],
        imported_counts={"sources": len(imported), "claims": 0, "evidence": 0},
        human_review_required=True,
        response={"status": status, "provider_count": len(results), "imported_count": len(imported)},
    )
    return {"ok": status == "succeeded", **payload, **paths, "imported": imported, "bridge_run": bridge_run}


def check_external_researcher_automation_profiles(
    root: str | Path,
    *,
    automation_plan: str | Path = "",
    question: str | None = None,
    clarification_answers: str = "",
    providers: str | list[str] | None = None,
    source_policy: str = "",
    output_language: str = "中文",
    profile_config_path: str = "",
    followup_wait_seconds: int = 10,
    max_wait_seconds: int = 900,
    live: bool = False,
    headless: bool = False,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    plan = _load_or_create_automation_plan(
        root,
        automation_plan=automation_plan,
        question=question,
        clarification_answers=clarification_answers,
        providers=providers,
        source_policy=source_policy,
        output_language=output_language,
        profile_config_path=profile_config_path,
        followup_wait_seconds=followup_wait_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    results = [
        preflight_provider_profile(
            profile,
            live=live,
            headless=headless,
            timeout_seconds=timeout_seconds,
            click_activation=live,
        )
        for profile in plan.get("provider_profiles", [])
    ]
    blocking = [row for row in results if row.get("status") not in {"configured", "ready"} or row.get("blockers")]
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "automation_preflight",
        "created_at": now_iso(),
        "live": bool(live),
        "question": plan.get("question", ""),
        "plan_path": plan.get("json_path", str(automation_plan or "")),
        "provider_count": len(results),
        "blocking_count": len(blocking),
        "results": results,
        "operator_boundary": "Live preflight may open provider pages and click mode labels, but it does not submit a research prompt.",
    }
    paths = _write_external_artifacts(root, "external-researcher-automation-preflight", payload, markdown=_render_preflight_markdown(payload))
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="check_external_researcher_automation_profiles",
        request={"automation_plan": payload["plan_path"], "live": live, "headless": headless},
        command="preflight external researcher provider profiles without submitting research",
        status="succeeded" if not blocking else "needs_human",
        artifact_paths=[paths["json_path"], paths["markdown_path"]],
        human_review_required=bool(blocking) or live,
        response={"provider_count": len(results), "blocking_count": len(blocking), "live": live},
    )
    return {"ok": not blocking, **payload, **paths, "bridge_run": bridge_run}


def write_external_researcher_profile_template(root: str | Path, *, output_path: str | Path | None = None) -> dict[str, Any]:
    paths = ensure_project_dirs(root)
    target = Path(output_path) if output_path else paths["root"] / "config" / "external-researcher-profiles.json"
    result = render_profile_config_template(target)
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="write_external_researcher_profile_template",
        request={"output_path": str(target)},
        command="write editable browser automation provider profile template",
        status="succeeded",
        artifact_paths=[str(target)],
        human_review_required=True,
        response=result,
    )
    return {**result, "bridge_run": bridge_run}


def prepare_external_researcher_login_profiles(
    root: str | Path,
    *,
    providers: str | list[str] | None = None,
    automation_plan: str | Path = "",
    profile_config_path: str = "",
    keep_open_seconds: int = 600,
    timeout_seconds: int = 45,
    headless: bool = False,
    live: bool = False,
) -> dict[str, Any]:
    plan = _load_or_create_automation_plan(
        root,
        automation_plan=automation_plan,
        question=None,
        clarification_answers="",
        providers=providers,
        source_policy="",
        output_language="中文",
        profile_config_path=profile_config_path,
        followup_wait_seconds=10,
        max_wait_seconds=900,
    )
    profiles = list(plan.get("provider_profiles", []))
    results = (
        open_provider_login_profiles(
            profiles,
            keep_open_seconds=keep_open_seconds,
            headless=headless,
            timeout_seconds=timeout_seconds,
        )
        if live
        else [
            {
                "provider": profile.get("provider"),
                "key": profile.get("key"),
                "status": "planned",
                "url": profile.get("url"),
                "user_data_dir": profile.get("user_data_dir"),
                "keep_open_seconds": int(keep_open_seconds),
            }
            for profile in profiles
        ]
    )
    blocking = [row for row in results if row.get("status") not in {"planned", "opened"}]
    payload = {
        "schema": EXTERNAL_RESEARCHER_SCHEMA,
        "kind": "login_profile_prep",
        "created_at": now_iso(),
        "live": bool(live),
        "plan_path": plan.get("json_path", str(automation_plan or "")),
        "provider_count": len(results),
        "blocking_count": len(blocking),
        "keep_open_seconds": int(keep_open_seconds),
        "results": results,
        "operator_boundary": "This mode opens authorized provider pages for manual login/profile setup. It does not submit a research prompt.",
    }
    paths = _write_external_artifacts(root, "external-researcher-login-profile-prep", payload, markdown=_render_login_profile_prep_markdown(payload))
    bridge_run = create_bridge_run(
        root,
        tool="external-researcher",
        action="prepare_external_researcher_login_profiles",
        request={"providers": plan.get("providers", []), "live": live, "keep_open_seconds": keep_open_seconds},
        command="open external researcher provider login/profile setup windows" if live else "plan external researcher provider login/profile setup windows",
        status="needs_human" if live or blocking else "planned",
        artifact_paths=[paths["json_path"], paths["markdown_path"]],
        human_review_required=True,
        response={"provider_count": len(results), "blocking_count": len(blocking), "live": live},
    )
    return {"ok": not blocking, **payload, **paths, "bridge_run": bridge_run}


def list_external_researcher_reports(root: str | Path, *, include_legacy: bool = False) -> dict[str, Any]:
    root_dir = ensure_project_dirs(root)["root"]
    run_dir = root_dir / "tool-runs"
    draft_dir = root_dir / "drafts" / "external-researcher"
    current_project = _current_project_identity(root)
    current_project_id = current_project.get("project_id", "")
    rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("external-researcher-report-*.json")):
        data = _read_external_report_json(path)
        if data is None:
            continue
        if not _report_belongs_to_current_project(data, current_project_id, include_legacy=include_legacy):
            continue
        rows.append(_report_listing_row(data, path, draft=False))
    for path in (sorted(draft_dir.glob("*.json")) if draft_dir.exists() else []):
        data = _read_external_report_json(path)
        if data is None:
            continue
        if not _report_belongs_to_current_project(data, current_project_id, include_legacy=include_legacy):
            continue
        rows.append(_report_listing_row(data, path, draft=True))
    latest_by_provider: dict[str, dict[str, Any]] = {}
    for row in rows:
        provider = str(row.get("provider") or "External researcher")
        existing = latest_by_provider.get(provider)
        if existing is None or _report_sort_key(row) >= _report_sort_key(existing):
            latest_by_provider[provider] = row
    reports = sorted(latest_by_provider.values(), key=lambda row: str(row.get("created_at") or ""))
    return {"ok": True, "schema": EXTERNAL_RESEARCHER_SCHEMA, "reports": reports, "count": len(reports)}


def _current_project_identity(root: str | Path) -> dict[str, str]:
    try:
        project = load_project(root)
    except Exception:
        return {"project_id": "", "question": ""}
    return {"project_id": str(project.id or ""), "question": str(project.question or "")}


def _report_belongs_to_current_project(data: dict[str, Any], current_project_id: str, *, include_legacy: bool) -> bool:
    if not current_project_id:
        return True
    report_project_id = str(data.get("project_id") or "")
    if not report_project_id:
        return include_legacy
    return report_project_id == current_project_id


def _read_external_report_json(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _report_listing_row(data: dict[str, Any], path: Path, *, draft: bool) -> dict[str, Any]:
    return {
        "project_id": str(data.get("project_id") or ""),
        "question": str(data.get("question") or ""),
        "provider": str(data.get("provider") or "External researcher"),
        "report_url": str(data.get("report_url") or ""),
        "notes": str(data.get("notes") or ""),
        "json_path": str(path),
        "markdown_path": str(path.with_suffix(".md")),
        "report_text": str(data.get("report_text") or ""),
        "created_at": str(data.get("created_at") or ""),
        "draft": bool(data.get("draft", draft)),
    }


def _report_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    return (str(row.get("created_at") or ""), 0 if row.get("draft") else 1)


def _provider_slug(provider: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", provider).strip("-")
    return slug or "external-researcher"


def _load_or_create_automation_plan(
    root: str | Path,
    *,
    automation_plan: str | Path = "",
    question: str | None,
    clarification_answers: str,
    providers: str | list[str] | None,
    source_policy: str,
    output_language: str,
    profile_config_path: str,
    followup_wait_seconds: int,
    max_wait_seconds: int,
) -> dict[str, Any]:
    if automation_plan:
        path = Path(automation_plan)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("automation_plan must contain a JSON object")
        data["json_path"] = str(path)
        data["markdown_path"] = str(path.with_suffix(".md"))
        return data
    return plan_external_researcher_automation(
        root,
        question=question,
        clarification_answers=clarification_answers,
        providers=providers,
        source_policy=source_policy,
        output_language=output_language,
        profile_config_path=profile_config_path,
        followup_wait_seconds=followup_wait_seconds,
        max_wait_seconds=max_wait_seconds,
    )


def default_followup_answer(question: str, *, source_policy: str = "") -> str:
    policy = str(source_policy or "").strip() or "优先使用官方文档、权威机构、论文/报告、主流媒体；遇到不确定或冲突时请标注。"
    return (
        "请按原始研究问题继续推进。范围以用户最初问题为准；如果有多个解释，请选择最能回答问题且最保守的解释。"
        f"来源策略：{policy} "
        "输出中文报告，保留关键来源链接、重要分歧、待验证点和你的假设。不要为了完整性编造信息。"
    )


def _clarification_questions(question: str) -> list[str]:
    return [
        "这次研究最终要支持什么决策或输出？",
        "时间范围、地域范围、行业/人群边界是什么？",
        "哪些来源必须优先，哪些来源应排除？",
        "是否需要处理附件、本地材料或指定网页？",
        "报告需要哪些固定栏目或格式？",
        "哪些结论需要特别谨慎，不足证据时宁可标注不确定？",
    ]


def _render_deep_research_prompt(question: str, *, clarification_answers: str, source_policy: str, output_language: str) -> str:
    policy = source_policy.strip() or "优先官方、论文、权威报告、主流媒体和一手数据；避免低质量 SEO 页面；无法确认时明确标注不确定。"
    answers = clarification_answers.strip() or "暂无额外澄清；请先按原始问题作合理假设，并在报告中列出这些假设。"
    return "\n".join(
        [
            "请使用你的深度研究/深度搜索模式完成以下任务。",
            "",
            "## 原始问题",
            question,
            "",
            "## 已澄清背景",
            answers,
            "",
            "## 来源策略",
            policy,
            "",
            "## 输出要求",
            f"- 使用{output_language}输出。",
            "- 先给执行摘要，再给详细分析。",
            "- 单独列出共识、分歧、证据不足、需要人工复核的点。",
            "- 每个关键事实尽量给出可打开的来源链接。",
            "- 不要把引用链接当作已验证证据；如果来源只间接支持，请明确说明。",
            "- 如果你需要继续追问，请只问必要问题；如果无人回答，请按最保守假设继续，并把假设写入报告。",
        ]
    )


def _provider_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return DEFAULT_PROVIDERS[:]
    if isinstance(value, str):
        rows = [item.strip() for item in value.replace("，", ",").split(",")]
    else:
        rows = [str(item).strip() for item in value]
    return [item for item in rows if item] or DEFAULT_PROVIDERS[:]


def _write_external_artifacts(root: str | Path, prefix: str, payload: dict[str, Any], *, markdown: str) -> dict[str, str]:
    paths = ensure_project_dirs(root)
    run_dir = paths["root"] / "tool-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    stem = _unique_stem(run_dir, f"{prefix}-{now_iso().replace(':', '-')}")
    json_path = run_dir / f"{stem}.json"
    markdown_path = run_dir / f"{stem}.md"
    write_json(json_path, payload)
    markdown_path.write_text(markdown, encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def _unique_stem(directory: Path, stem: str) -> str:
    candidate = stem
    index = 2
    while (directory / f"{candidate}.json").exists() or (directory / f"{candidate}.md").exists():
        candidate = f"{stem}-{index}"
        index += 1
    return candidate


def _render_plan_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# External Researcher Plan",
        "",
        "## Boundary",
        "",
        "- Web deep research providers are external researchers.",
        "- This artifact is a prompt and operation handoff, not verified evidence.",
        "",
        "## Providers",
        "",
    ]
    lines.extend(f"- {provider}" for provider in payload.get("providers", []))
    lines.extend(["", "## Clarification Questions", ""])
    lines.extend(f"{index}. {question}" for index, question in enumerate(payload.get("clarification_questions", []), start=1))
    lines.extend(["", "## Deep Research Prompt", "", "```text", str(payload.get("deep_research_prompt") or ""), "```", "", "## Default Follow-up Answer", "", str(payload.get("followup_default_answer") or ""), ""])
    return "\n".join(lines)


def _render_automation_plan_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# External Researcher Browser Automation Plan",
        "",
        "- Status: planned",
        "- Boundary: authorized logged-in browser sessions only; no login/CAPTCHA bypass.",
        f"- Follow-up wait: {payload.get('followup_wait_seconds')} seconds",
        f"- Max wait per provider: {payload.get('max_wait_seconds')} seconds",
        "",
        "## Providers",
        "",
    ]
    for profile in payload.get("provider_profiles", []):
        lines.extend(
            [
                f"### {profile.get('provider')}",
                "",
                f"- URL: {profile.get('url') or '_not configured_'}",
                f"- User data dir: `{profile.get('user_data_dir')}`",
                f"- Activate texts: {', '.join(profile.get('activate_texts') or [])}",
                f"- Ready: {profile.get('ready')}",
                "",
            ]
        )
    lines.extend(["## Deep Research Prompt", "", "```text", str(payload.get("deep_research_prompt") or ""), "```", ""])
    return "\n".join(lines)


def _render_automation_run_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# External Researcher Browser Automation Run",
        "",
        f"- Created: {payload.get('created_at')}",
        f"- Imported reports: {payload.get('imported_count')}",
        "- Boundary: collected outputs are candidate context only.",
        "",
        "## Provider Results",
        "",
    ]
    for result in payload.get("results", []):
        lines.extend(
            [
                f"### {result.get('provider')}",
                "",
                f"- Status: {result.get('status')}",
                f"- URL: {result.get('url')}",
                f"- Error: {result.get('error') or ''}",
                f"- Follow-up: `{json.dumps(result.get('followup') or {}, ensure_ascii=False)}`",
                f"- Report chars: {len(str(result.get('report_text') or ''))}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_preflight_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# External Researcher Automation Preflight",
        "",
        f"- Live browser check: {payload.get('live')}",
        f"- Provider count: {payload.get('provider_count')}",
        f"- Blocking count: {payload.get('blocking_count')}",
        "- Boundary: preflight does not submit a research prompt.",
        "",
        "## Provider Checks",
        "",
    ]
    for result in payload.get("results", []):
        lines.extend(
            [
                f"### {result.get('provider')}",
                "",
                f"- Status: {result.get('status')}",
                f"- URL: {result.get('url')}",
                f"- Enabled: {result.get('enabled')}",
                f"- Input visible: {result.get('input_visible', '')}",
                f"- Activation labels present: {', '.join(result.get('activation_texts_present') or [])}",
                f"- Blockers: {', '.join(result.get('blockers') or [])}",
                f"- Recovery: {result.get('recovery_hint') or result.get('error') or ''}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_login_profile_prep_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# External Researcher Login Profile Prep",
        "",
        f"- Live: {payload.get('live')}",
        f"- Provider count: {payload.get('provider_count')}",
        f"- Keep open seconds: {payload.get('keep_open_seconds')}",
        "- Boundary: this opens login/setup windows only and does not submit research.",
        "",
        "## Provider Windows",
        "",
    ]
    for result in payload.get("results", []):
        lines.extend(
            [
                f"### {result.get('provider')}",
                "",
                f"- Status: {result.get('status')}",
                f"- URL: {result.get('url')}",
                f"- Profile: `{result.get('user_data_dir')}`",
                f"- Error: {result.get('error') or result.get('navigation_error') or ''}",
                f"- Recovery: {result.get('recovery_hint') or ''}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_followup_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# External Researcher Follow-up",
            "",
            f"- Answer source: {payload.get('answer_source')}",
            f"- Auto after seconds: {payload.get('auto_after_seconds')}",
            "",
            "## Provider Follow-up Question",
            "",
            str(payload.get("followup_question") or ""),
            "",
            "## Answer",
            "",
            str(payload.get("answer") or ""),
            "",
        ]
    )


def _render_report_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload.get('provider')} External Research Report",
        "",
        "- Status: candidate context only",
        f"- URL: {payload.get('report_url') or ''}",
        f"- Created: {payload.get('created_at') or ''}",
        "",
        "## Notes",
        "",
        str(payload.get("notes") or "_No notes._"),
        "",
        "## Prompt",
        "",
        str(payload.get("prompt_text") or "_Prompt not recorded._"),
        "",
        "## Report",
        "",
        str(payload.get("report_text") or ""),
        "",
    ]
    return "\n".join(lines)


def _render_aggregate_markdown(root: str | Path, payload: dict[str, Any]) -> str:
    project = load_project(root)
    reports = payload.get("reports", [])
    lines = [
        "# External Researcher Aggregate",
        "",
        f"- Research question: {project.question}",
        f"- Report count: {len(reports)}",
        "- Boundary: external reports are candidate context only; sentence-level evidence still requires local verification.",
        "",
        "## Collection Summary",
        "",
    ]
    if not reports:
        lines.append("- No provider reports collected yet.")
    for index, report in enumerate(reports, start=1):
        lines.append(f"{index}. {report.get('provider')} - {report.get('markdown_path')}")
    lines.extend(
        [
            "",
            "## Synthesis Prompt For A Separate Summarizer",
            "",
            "请综合下面所有外部深度研究报告，输出中文 Markdown：",
            "- 先列共识结论。",
            "- 再列分歧点和可能原因。",
            "- 对每个关键事实标注来自哪个外部报告；不要把外部报告的引用当作已验证证据。",
            "- 最后列出需要进入本地 evidence 审核的候选主张和来源链接。",
            "",
            "## Provider Reports",
            "",
        ]
    )
    for report in reports:
        lines.extend(
            [
                f"### {report.get('provider')}",
                "",
                f"- Artifact: {report.get('markdown_path')}",
                f"- URL: {report.get('report_url') or ''}",
                "",
                str(report.get("report_text") or "").strip() or "_Empty report text._",
                "",
            ]
        )
    return "\n".join(lines)
