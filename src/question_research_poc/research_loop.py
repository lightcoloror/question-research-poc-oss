from __future__ import annotations

from pathlib import Path
from typing import Any

from .ai_research_bridge import (
    ai_research_status,
    fetch_ai_research_deepen_suggestions,
    fetch_ai_research_run_quality,
    run_ai_research_agent_research,
)
from .models import now_iso
from .orchestrator import list_records
from .research_gaps import ACTIONABLE_STATUS, analyze_research_gaps
from .research_progress import normalize_topic, evidence_snapshot, progress_delta
from .storage import append_jsonl, load_project, read_json, write_json


TERMINAL_STATUSES = {"ready_for_human_review", "needs_more_manual_input", "blocked_bridge_down", "stopped_budget_limit"}
RESEARCH_LOOP_SCHEMA = "question_research_loop_run.v1"
RESEARCH_LOOP_LIST_SCHEMA = "question_research_loop_list.v1"
RESEARCH_LOOP_REVIEW_PACK_SCHEMA = "question_research_loop_review_pack.v1"


def run_research_loop(
    root: str | Path,
    *,
    query: str | None = None,
    mode: str = "academic",
    rounds: int = 3,
    max_results: int = 8,
    max_queries_per_round: int = 3,
    no_network: bool = False,
    fetch: bool = True,
    base_url: str | None = None,
    timeout_seconds: int = 240,
    status_timeout_seconds: int = 5,
) -> dict[str, Any]:
    project = load_project(root)
    root_path = Path(root)
    topic = str(query or project.question)
    artifact_dir = root_path / "state" / "research-loop" / now_iso().replace(":", "-")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    status = ai_research_status(base_url, timeout_seconds=status_timeout_seconds)
    if not _bridge_ready(status):
        result = _result(
            root_path,
            artifact_dir,
            topic=topic,
            status="blocked_bridge_down",
            stop_reason="bridge_down",
            preflight=status,
            rounds=[],
            gaps=[],
            latest_job_id="",
            latest_run_id="",
            fallback_used=False,
            human_review_required=True,
        )
        _write_loop_artifacts(result, artifact_dir)
        return result

    loop_rounds: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    latest_job_id = ""
    latest_run_id = ""
    fallback_used = False
    zero_growth_streak = 0
    current_queries = [{"query": topic, "gap_id": "initial", "priority": "P1", "reason": "initial query"}]
    used_queries: set[str] = set()
    last_quality: dict[str, Any] = {}
    last_deepen: dict[str, Any] = {}
    stop_reason = "round_limit"

    for round_index in range(1, max(1, int(rounds)) + 1):
        if round_index > 1:
            gap_analysis = analyze_research_gaps(
                root_path,
                query=topic,
                ai_quality=last_quality,
                deepen_suggestions=last_deepen,
                max_queries_per_round=max_queries_per_round,
            )
            all_gaps = gap_analysis["gaps"]
            current_queries = _new_queries(gap_analysis["actionable_queries"], used_queries)
            if not current_queries:
                stop_reason = "no_actionable_search_gap"
                break

        before_counts = _counts(root_path)
        before_evidence = _evidence_snapshot(root_path)
        jobs: list[dict[str, Any]] = []
        round_quality: list[dict[str, Any]] = []
        round_deepen: list[dict[str, Any]] = []

        for planned in current_queries[: max(1, int(max_queries_per_round))]:
            used_queries.add(_norm(planned.get("query") or topic))
            run = run_ai_research_agent_research(
                root_path,
                query=str(planned.get("query") or topic),
                mode=mode,
                max_results=max_results,
                no_network=no_network,
                fetch=fetch,
                import_results=True,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                auto_verify=True,
            )
            latest_job_id = str(run.get("job_id") or latest_job_id)
            latest_run_id = str(run.get("run_id") or latest_run_id)
            fallback_used = fallback_used or bool(run.get("fallback_used", False))
            job_summary = {
                "query": planned.get("query") or topic,
                "gap_id": planned.get("gap_id", ""),
                "ok": bool(run.get("ok")),
                "job_id": str(run.get("job_id") or ""),
                "run_id": str(run.get("run_id") or ""),
                "fallback_used": bool(run.get("fallback_used", False)),
                "failure_reason": str(run.get("failure_reason") or ""),
                "imported_counts": ((run.get("bridge_run") or {}).get("imported_counts") or {}),
                "bridge_run_id": (run.get("bridge_run") or {}).get("id", ""),
            }
            jobs.append(job_summary)
            if not run.get("ok"):
                stop_reason = "bridge_down" if "refused" in job_summary["failure_reason"].lower() or "timed out" in job_summary["failure_reason"].lower() else "job_failed"
                loop_rounds.append(_round(round_index, planned_queries=current_queries, jobs=jobs, quality=round_quality, deepen=round_deepen, before=before_counts, after=_counts(root_path)))
                result = _result(
                    root_path,
                    artifact_dir,
                    topic=topic,
                    status="blocked_bridge_down" if stop_reason == "bridge_down" else "needs_more_manual_input",
                    stop_reason=stop_reason,
                    preflight=status,
                    rounds=loop_rounds,
                    gaps=all_gaps,
                    latest_job_id=latest_job_id,
                    latest_run_id=latest_run_id,
                    fallback_used=fallback_used,
                    human_review_required=True,
                )
                _write_loop_artifacts(result, artifact_dir)
                return result
            if run.get("run_id"):
                quality, deepen = _fetch_run_gap_signals(str(run["run_id"]), base_url=base_url, max_queries=max_queries_per_round)
                if quality:
                    round_quality.append(quality)
                    last_quality = quality
                if deepen:
                    round_deepen.append(deepen)
                    last_deepen = deepen

        after_counts = _counts(root_path)
        growth = {key: after_counts[key] - before_counts[key] for key in before_counts}
        evidence_gain = progress_delta(before_evidence, _evidence_snapshot(root_path))
        zero_growth_streak = zero_growth_streak + 1 if not evidence_gain['meaningful_gain'] else 0
        gap_analysis = analyze_research_gaps(
            root_path,
            query=topic,
            ai_quality=last_quality,
            deepen_suggestions=last_deepen,
            max_queries_per_round=max_queries_per_round,
        )
        all_gaps = gap_analysis["gaps"]
        next_queries = _new_queries(gap_analysis["actionable_queries"], used_queries)
        loop_rounds.append(
            _round(
                round_index,
                planned_queries=current_queries,
                jobs=jobs,
                quality=round_quality,
                deepen=round_deepen,
                before=before_counts,
                after=after_counts,
                gaps=all_gaps,
                next_queries=next_queries,
                evidence_gain=evidence_gain,
            )
        )
        if not next_queries:
            stop_reason = "no_actionable_search_gap"
            break
        if zero_growth_streak >= 2:
            stop_reason = "no_new_source_or_evidence"
            break
        stop_reason = "round_limit"

    final_status = _final_status(stop_reason, all_gaps)
    result = _result(
        root_path,
        artifact_dir,
        topic=topic,
        status=final_status,
        stop_reason=stop_reason if stop_reason != "round_limit" or len(loop_rounds) >= int(rounds) else "no_actionable_search_gap",
        preflight=status,
        rounds=loop_rounds,
        gaps=all_gaps,
        latest_job_id=latest_job_id,
        latest_run_id=latest_run_id,
        fallback_used=fallback_used,
        human_review_required=True,
    )
    _write_loop_artifacts(result, artifact_dir)
    return result


def list_research_loops(root: str | Path, *, limit: int = 20) -> dict[str, Any]:
    root_path = Path(root)
    loop_root = root_path / "state" / "research-loop"
    loops: list[dict[str, Any]] = []
    if loop_root.exists():
        for artifact_dir in sorted([path for path in loop_root.iterdir() if path.is_dir()], key=lambda item: item.stat().st_mtime, reverse=True):
            loop_json = artifact_dir / "loop.json"
            if not loop_json.exists():
                continue
            try:
                payload = _normalize_loop_result(read_json(loop_json), root_path, artifact_dir)
            except Exception as exc:
                payload = {
                    "id": artifact_dir.name,
                    "artifact_dir": str(artifact_dir),
                    "status": "unreadable",
                    "error": str(exc),
                }
            loops.append(_loop_summary(payload, artifact_dir))
            if len(loops) >= max(1, int(limit)):
                break
    return {
        "ok": True,
        "schema": RESEARCH_LOOP_LIST_SCHEMA,
        "root": str(root_path),
        "loop_root": str(loop_root),
        "loops": loops,
        "count": len(loops),
        "human_review_required": any(bool(loop.get("human_review_required")) for loop in loops),
    }


def read_research_loop(root: str | Path, loop_id: str = "") -> dict[str, Any]:
    root_path = Path(root)
    artifact_dir = _resolve_loop_dir(root_path, loop_id)
    if not artifact_dir:
        return {
            "ok": False,
            "schema": RESEARCH_LOOP_SCHEMA,
            "root": str(root_path),
            "error": "research loop not found",
            "recovery_hint": "Run research-loop first or pass an existing loop id/path from list-research-loops.",
            "human_review_required": True,
            "candidate_only": True,
        }
    loop_json = artifact_dir / "loop.json"
    if not loop_json.exists():
        return {
            "ok": False,
            "schema": RESEARCH_LOOP_SCHEMA,
            "root": str(root_path),
            "id": artifact_dir.name,
            "artifact_dir": str(artifact_dir),
            "error": "loop.json missing",
            "recovery_hint": "The artifact directory exists but the canonical loop.json is missing.",
            "human_review_required": True,
            "candidate_only": True,
        }
    result = _normalize_loop_result(read_json(loop_json), root_path, artifact_dir)
    result["review_pack"] = _review_pack_status(artifact_dir)
    return result


def export_research_loop_review_pack(root: str | Path, *, loop_id: str = "", output_dir: str | Path | None = None) -> dict[str, Any]:
    root_path = Path(root)
    artifact_dir = _resolve_loop_dir(root_path, loop_id)
    if not artifact_dir:
        return {
            "ok": False,
            "schema": RESEARCH_LOOP_REVIEW_PACK_SCHEMA,
            "root": str(root_path),
            "error": "research loop not found",
            "recovery_hint": "Run research-loop first, then export the review pack.",
            "candidate_only": True,
            "human_review_required": True,
        }
    result = read_research_loop(root_path, artifact_dir.name)
    if not result.get("ok"):
        return {**result, "schema": RESEARCH_LOOP_REVIEW_PACK_SCHEMA}
    pack_dir = Path(output_dir) if output_dir else artifact_dir / "review-pack"
    files = _write_review_pack(result, pack_dir)
    return {
        "ok": True,
        "schema": RESEARCH_LOOP_REVIEW_PACK_SCHEMA,
        "root": str(root_path),
        "id": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "output_dir": str(pack_dir),
        "files": files,
        "candidate_only": True,
        "verified_evidence_created": False,
        "human_review_required": True,
        "review_gate_required": True,
        "boundary": "Review pack only. It summarizes candidate imports and gaps; it does not create final answers, mark source quality, or verify evidence.",
    }


def _bridge_ready(status: dict[str, Any]) -> bool:
    return bool(status.get("metadata_available") and status.get("live_ok") and status.get("available"))


def _new_queries(queries: list[dict[str, Any]], used_queries: set[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in queries:
        normalized = _norm(item.get("query", ""))
        if not normalized or normalized in used_queries or normalized in seen:
            continue
        seen.add(normalized)
        output.append(item)
    return output


def _norm(value: Any) -> str:
    return normalize_topic(value)


def _fetch_run_gap_signals(run_id: str, *, base_url: str | None, max_queries: int) -> tuple[dict[str, Any], dict[str, Any]]:
    quality: dict[str, Any] = {}
    deepen: dict[str, Any] = {}
    try:
        quality = fetch_ai_research_run_quality(run_id, base_url=base_url)
    except Exception as exc:
        quality = {"overall": "error", "run_id": run_id, "error": str(exc)}
    try:
        deepen = fetch_ai_research_deepen_suggestions(run_id, base_url=base_url, max_queries=max_queries)
    except Exception as exc:
        deepen = {"overall": "error", "run_id": run_id, "error": str(exc), "deepen_suggestions": []}
    return quality, deepen


def _counts(root: Path) -> dict[str, int]:
    return {
        "sources": len(list_records(root, "sources")),
        "claims": len(list_records(root, "claims")),
        "evidence": len(list_records(root, "evidence")),
    }


def _evidence_snapshot(root: Path) -> dict[str, set]:
    return evidence_snapshot(list_records(root, 'sources'), list_records(root, 'claims'), list_records(root, 'evidence'))


def _round(
    round_index: int,
    *,
    planned_queries: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    quality: list[dict[str, Any]],
    deepen: list[dict[str, Any]],
    before: dict[str, int],
    after: dict[str, int],
    gaps: list[dict[str, Any]] | None = None,
    next_queries: list[dict[str, Any]] | None = None,
    evidence_gain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "round_index": round_index,
        "planned_queries": planned_queries,
        "jobs": jobs,
        "quality": quality,
        "deepen_suggestions": deepen,
        "counts_before": before,
        "counts_after": after,
        "growth": {key: after[key] - before[key] for key in before},
        "evidence_gain": evidence_gain or {},
        "gaps_after": gaps or [],
        "next_queries": next_queries or [],
    }


def _final_status(stop_reason: str, gaps: list[dict[str, Any]]) -> str:
    if stop_reason == "bridge_down":
        return "blocked_bridge_down"
    actionable = [gap for gap in gaps if gap.get("status") == ACTIONABLE_STATUS]
    if stop_reason == "round_limit" and actionable:
        return "stopped_budget_limit"
    if stop_reason == "no_actionable_search_gap" and actionable:
        return "needs_more_manual_input"
    if stop_reason == "no_new_source_or_evidence" and actionable:
        return "needs_more_manual_input"
    return "ready_for_human_review"


def _result(
    root: Path,
    artifact_dir: Path,
    *,
    topic: str,
    status: str,
    stop_reason: str,
    preflight: dict[str, Any],
    rounds: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    latest_job_id: str,
    latest_run_id: str,
    fallback_used: bool,
    human_review_required: bool,
) -> dict[str, Any]:
    artifact_paths = [
        str(artifact_dir / "loop.json"),
        str(artifact_dir / "gap-ledger.jsonl"),
        str(artifact_dir / "rounds.jsonl"),
        str(artifact_dir / "summary.md"),
        str(artifact_dir / "review-pack" / "rounds.md"),
        str(artifact_dir / "review-pack" / "gap-ledger.md"),
        str(artifact_dir / "review-pack" / "candidate-import-table.md"),
        str(artifact_dir / "review-pack" / "review-next-actions.md"),
    ]
    return {
        "ok": status in TERMINAL_STATUSES,
        "schema": RESEARCH_LOOP_SCHEMA,
        "root": str(root),
        "id": artifact_dir.name,
        "query": topic,
        "status": status,
        "stop_reason": stop_reason,
        "round_count": len(rounds),
        "rounds": rounds,
        "gaps": gaps,
        "job_id": latest_job_id,
        "run_id": latest_run_id,
        "fallback_used": bool(fallback_used),
        "preflight": preflight,
        "backend_mode": "full_research" if _bridge_ready(preflight) else "blocked",
        "candidate_only": True,
        "verified_evidence_created": False,
        "review_gate_required": True,
        "imported_counts": _aggregate_imported_counts(rounds),
        "human_review_required": human_review_required,
        "artifact_dir": str(artifact_dir),
        "artifact_paths": artifact_paths,
    }


def _write_loop_artifacts(result: dict[str, Any], artifact_dir: Path) -> None:
    write_json(artifact_dir / "loop.json", result)
    append_jsonl(artifact_dir / "gap-ledger.jsonl", result.get("gaps") or [])
    append_jsonl(artifact_dir / "rounds.jsonl", result.get("rounds") or [])
    (artifact_dir / "summary.md").write_text(_summary_markdown(result), encoding="utf-8")
    _write_review_pack(result, artifact_dir / "review-pack")


def _summary_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Research Loop: {result.get('query', '')}",
        "",
        f"- Status: `{result.get('status')}`",
        f"- Stop reason: `{result.get('stop_reason')}`",
        f"- Latest job: `{result.get('job_id') or 'none'}`",
        f"- Latest run: `{result.get('run_id') or 'none'}`",
            f"- Fallback used: `{result.get('fallback_used')}`",
            f"- Candidate only: `{result.get('candidate_only')}`",
            f"- Verified evidence created: `{result.get('verified_evidence_created')}`",
            f"- Human review required: `{result.get('human_review_required')}`",
        "",
        "## Rounds",
        "",
    ]
    for item in result.get("rounds") or []:
        lines.append(f"- Round {item.get('round_index')}: {len(item.get('jobs') or [])} job(s), growth `{item.get('growth')}`")
    if not result.get("rounds"):
        lines.append("- No research round ran.")
    lines.extend(["", "## Gaps", ""])
    gaps = result.get("gaps") or []
    for gap in gaps:
        lines.append(f"- `{gap.get('priority')}` `{gap.get('type')}` `{gap.get('status')}`: {gap.get('title')}")
    if not gaps:
        lines.append("- No remaining gap recorded.")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This loop only imports candidate sources/evidence and gap records. It does not mark evidence as verified or turn claims into final facts.",
        ]
    )
    return "\n".join(lines) + "\n"


def _resolve_loop_dir(root: Path, loop_id: str = "") -> Path | None:
    loop_root = root / "state" / "research-loop"
    if loop_id:
        candidate = Path(loop_id)
        if candidate.exists() and candidate.is_dir():
            return candidate
        candidate = loop_root / loop_id
        return candidate if candidate.exists() and candidate.is_dir() else None
    if not loop_root.exists():
        return None
    rows = [path for path in loop_root.iterdir() if path.is_dir() and (path / "loop.json").exists()]
    return sorted(rows, key=lambda item: item.stat().st_mtime, reverse=True)[0] if rows else None


def _normalize_loop_result(value: object, root: Path, artifact_dir: Path) -> dict[str, Any]:
    result = dict(value) if isinstance(value, dict) else {}
    rounds = result.get("rounds") if isinstance(result.get("rounds"), list) else []
    preflight = result.get("preflight") if isinstance(result.get("preflight"), dict) else {}
    result.setdefault("ok", str(result.get("status") or "") in TERMINAL_STATUSES)
    result["schema"] = RESEARCH_LOOP_SCHEMA
    result.setdefault("root", str(root))
    result.setdefault("id", artifact_dir.name)
    result.setdefault("artifact_dir", str(artifact_dir))
    result["round_count"] = int(result.get("round_count") or len(rounds))
    result.setdefault("backend_mode", "full_research" if _bridge_ready(preflight) else "blocked")
    result["candidate_only"] = True
    result["verified_evidence_created"] = False
    result["review_gate_required"] = True
    result["human_review_required"] = True
    result.setdefault("imported_counts", _aggregate_imported_counts(rounds))
    result["artifact_paths"] = _artifact_paths_for(artifact_dir)
    return result


def _loop_summary(payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    return {
        "id": str(payload.get("id") or artifact_dir.name),
        "query": str(payload.get("query") or ""),
        "status": str(payload.get("status") or "unknown"),
        "stop_reason": str(payload.get("stop_reason") or ""),
        "round_count": int(payload.get("round_count") or len(payload.get("rounds") or [])),
        "job_id": str(payload.get("job_id") or ""),
        "run_id": str(payload.get("run_id") or ""),
        "fallback_used": bool(payload.get("fallback_used", False)),
        "candidate_only": True,
        "verified_evidence_created": False,
        "human_review_required": True,
        "artifact_dir": str(artifact_dir),
        "artifact_paths": _artifact_paths_for(artifact_dir),
        "review_pack": _review_pack_status(artifact_dir),
    }


def _artifact_paths_for(artifact_dir: Path) -> list[str]:
    return [
        str(artifact_dir / "loop.json"),
        str(artifact_dir / "gap-ledger.jsonl"),
        str(artifact_dir / "rounds.jsonl"),
        str(artifact_dir / "summary.md"),
        str(artifact_dir / "review-pack" / "rounds.md"),
        str(artifact_dir / "review-pack" / "gap-ledger.md"),
        str(artifact_dir / "review-pack" / "candidate-import-table.md"),
        str(artifact_dir / "review-pack" / "review-next-actions.md"),
    ]


def _review_pack_status(artifact_dir: Path) -> dict[str, Any]:
    files = {
        "rounds": artifact_dir / "review-pack" / "rounds.md",
        "gap_ledger": artifact_dir / "review-pack" / "gap-ledger.md",
        "candidate_import_table": artifact_dir / "review-pack" / "candidate-import-table.md",
        "review_next_actions": artifact_dir / "review-pack" / "review-next-actions.md",
    }
    return {
        "output_dir": str(artifact_dir / "review-pack"),
        "complete": all(path.exists() for path in files.values()),
        "files": {key: str(path) for key, path in files.items()},
    }


def _write_review_pack(result: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "rounds": output_dir / "rounds.md",
        "gap_ledger": output_dir / "gap-ledger.md",
        "candidate_import_table": output_dir / "candidate-import-table.md",
        "review_next_actions": output_dir / "review-next-actions.md",
    }
    files["rounds"].write_text(_rounds_markdown(result), encoding="utf-8")
    files["gap_ledger"].write_text(_gap_ledger_markdown(result), encoding="utf-8")
    files["candidate_import_table"].write_text(_candidate_import_table_markdown(result), encoding="utf-8")
    files["review_next_actions"].write_text(_review_next_actions_markdown(result), encoding="utf-8")
    return {key: str(path) for key, path in files.items()}


def _rounds_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Research Loop Rounds: {result.get('query', '')}",
        "",
        f"- Status: `{result.get('status')}`",
        f"- Stop reason: `{result.get('stop_reason')}`",
        f"- Candidate only: `{result.get('candidate_only', True)}`",
        f"- Human review required: `{result.get('human_review_required', True)}`",
        "",
    ]
    rounds = result.get("rounds") or []
    for item in rounds:
        lines.extend(
            [
                f"## Round {item.get('round_index')}",
                "",
                f"- Growth: `{item.get('growth')}`",
                f"- Jobs: {len(item.get('jobs') or [])}",
                "",
                "| Query | Job | Run | Imported | Failure |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for job in item.get("jobs") or []:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(job.get("query", "")),
                        _md_cell(job.get("job_id", "")),
                        _md_cell(job.get("run_id", "")),
                        _md_cell(str(job.get("imported_counts") or {})),
                        _md_cell(job.get("failure_reason", "")),
                    ]
                )
                + " |"
            )
        lines.append("")
    if not rounds:
        lines.append("- No research round ran.")
    return "\n".join(lines).rstrip() + "\n"


def _gap_ledger_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Research Gap Ledger: {result.get('query', '')}",
        "",
        "| Priority | Type | Status | Title | Reason | Suggested queries |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    gaps = result.get("gaps") or []
    for gap in gaps:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(gap.get("priority", "")),
                    _md_cell(gap.get("type", "")),
                    _md_cell(gap.get("status", "")),
                    _md_cell(gap.get("title", "")),
                    _md_cell(gap.get("reason", "")),
                    _md_cell("; ".join(str(query) for query in gap.get("suggested_queries") or [])),
                ]
            )
            + " |"
        )
    if not gaps:
        lines.append("|  |  |  | No remaining gap recorded. |  |  |")
    return "\n".join(lines).rstrip() + "\n"


def _candidate_import_table_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Candidate Import Table: {result.get('query', '')}",
        "",
        "All imported material remains candidate-only until human review.",
        "",
        "| Round | Query | Bridge run | Sources | Claims | Evidence | Boundary |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    rows = 0
    for item in result.get("rounds") or []:
        for job in item.get("jobs") or []:
            counts = job.get("imported_counts") if isinstance(job.get("imported_counts"), dict) else {}
            rows += 1
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(item.get("round_index", "")),
                        _md_cell(job.get("query", "")),
                        _md_cell(job.get("bridge_run_id", "")),
                        _md_cell(counts.get("sources", 0)),
                        _md_cell(counts.get("claims", 0)),
                        _md_cell(counts.get("evidence", 0)),
                        "candidate only; review required",
                    ]
                )
                + " |"
            )
    if not rows:
        lines.append("|  |  |  | 0 | 0 | 0 | no imports |")
    return "\n".join(lines).rstrip() + "\n"


def _review_next_actions_markdown(result: dict[str, Any]) -> str:
    actionable = [gap for gap in result.get("gaps") or [] if gap.get("status") == ACTIONABLE_STATUS]
    review_only = [gap for gap in result.get("gaps") or [] if gap.get("status") != ACTIONABLE_STATUS]
    lines = [
        f"# Review Next Actions: {result.get('query', '')}",
        "",
        f"- Status: `{result.get('status')}`",
        f"- Stop reason: `{result.get('stop_reason')}`",
        f"- Candidate only: `{result.get('candidate_only', True)}`",
        f"- Verified evidence created: `{result.get('verified_evidence_created', False)}`",
        "",
        "## Human Review",
        "",
        "- Review newly imported sources before assigning source quality.",
        "- Review candidate evidence before using it in guarded final answers.",
        "- Do not publish a final answer from this pack alone.",
        "",
        "## Remaining Search Gaps",
        "",
    ]
    if actionable:
        lines.extend(f"- `{gap.get('priority')}` {gap.get('title')}: {gap.get('reason')}" for gap in actionable)
    else:
        lines.append("- No actionable search gap remains. Move to review queue instead of running another search loop.")
    lines.extend(["", "## Review-Only Gaps", ""])
    if review_only:
        lines.extend(f"- `{gap.get('priority')}` {gap.get('title')}: {gap.get('reason')}" for gap in review_only)
    else:
        lines.append("- No review-only gap recorded.")
    return "\n".join(lines).rstrip() + "\n"


def _aggregate_imported_counts(rounds: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"sources": 0, "claims": 0, "evidence": 0}
    for item in rounds:
        for job in item.get("jobs") or []:
            imported = job.get("imported_counts") if isinstance(job.get("imported_counts"), dict) else {}
            for key in counts:
                try:
                    counts[key] += int(imported.get(key) or 0)
                except (TypeError, ValueError):
                    continue
    return counts


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()
