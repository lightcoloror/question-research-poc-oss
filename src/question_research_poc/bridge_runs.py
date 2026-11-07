from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import new_id, now_iso
from .storage import write_json


BRIDGE_RUN_SCHEMA = "question_research_bridge_run.v1"
VALID_BRIDGE_STATUSES = {"planned", "running", "succeeded", "failed", "imported", "needs_human"}


def create_bridge_run(
    root: str | Path,
    *,
    tool: str,
    action: str,
    request: dict[str, Any] | None = None,
    command: list[str] | str | None = None,
    endpoint: str = "",
    status: str = "planned",
    artifact_paths: list[str] | None = None,
    imported_counts: dict[str, Any] | None = None,
    error: str = "",
    recovery_hint: str = "",
    human_review_required: bool = False,
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in VALID_BRIDGE_STATUSES:
        raise ValueError(f"invalid bridge run status: {status}")
    project_root = Path(root)
    run_id = new_id("bridge")
    run_dir = project_root / "state" / "tool-runs" / f"{now_iso().replace(':', '-')}-{_safe_slug(tool)}-{_safe_slug(action)}-{run_id.removeprefix('bridge_')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "result.json"
    record = {
        "ok": status not in {"failed", "needs_human"},
        "schema": BRIDGE_RUN_SCHEMA,
        "id": run_id,
        "root": str(project_root),
        "tool": tool,
        "action": action,
        "request": request or {},
        "command": command or "",
        "endpoint": endpoint,
        "status": status,
        "artifact_paths": artifact_paths or [],
        "imported_counts": imported_counts or {},
        "error": error,
        "recovery_hint": recovery_hint,
        "human_review_required": bool(human_review_required),
        "response": response or {},
        "created_at": now_iso(),
        "run_dir": str(run_dir),
        "path": str(result_path),
    }
    write_json(result_path, record)
    return record


def update_bridge_run(
    run: dict[str, Any],
    *,
    status: str | None = None,
    artifact_paths: list[str] | None = None,
    imported_counts: dict[str, Any] | None = None,
    error: str | None = None,
    recovery_hint: str | None = None,
    human_review_required: bool | None = None,
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status is not None:
        if status not in VALID_BRIDGE_STATUSES:
            raise ValueError(f"invalid bridge run status: {status}")
        run["status"] = status
        run["ok"] = status not in {"failed", "needs_human"}
    if artifact_paths is not None:
        run["artifact_paths"] = _dedupe([*run.get("artifact_paths", []), *artifact_paths])
    if imported_counts is not None:
        run["imported_counts"] = imported_counts
    if error is not None:
        run["error"] = error
    if recovery_hint is not None:
        run["recovery_hint"] = recovery_hint
    if human_review_required is not None:
        run["human_review_required"] = bool(human_review_required)
    if response is not None:
        run["response"] = response
    run["updated_at"] = now_iso()
    path = Path(str(run.get("path") or ""))
    if not path:
        raise ValueError("bridge run has no path")
    write_json(path, run)
    return run


def list_bridge_runs(
    root: str | Path,
    *,
    tool: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    project_root = Path(root)
    rows = [_normalize_run(path, project_root) for path in _run_paths(project_root)]
    rows = [row for row in rows if row]
    if tool:
        rows = [row for row in rows if row.get("tool") == tool]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    rows.sort(key=lambda row: str(row.get("created_at") or row.get("path") or ""), reverse=True)
    limited = rows[: max(int(limit), 1)]
    return {
        "ok": True,
        "schema": "question_research_bridge_runs.v1",
        "root": str(project_root),
        "runs": limited,
        "counts": _counts(rows),
        "human_review_required": any(row.get("human_review_required") for row in rows),
    }


def read_bridge_run(root: str | Path, run_id_or_path: str) -> dict[str, Any]:
    project_root = Path(root)
    target = str(run_id_or_path)
    for path in _run_paths(project_root):
        row = _normalize_run(path, project_root)
        if not row:
            continue
        if target in {str(row.get("id")), str(row.get("path")), str(path)}:
            return {"ok": True, "schema": "question_research_bridge_run_read.v1", "root": str(project_root), "run": row}
    raise ValueError(f"bridge run not found: {run_id_or_path}")


def retry_bridge_run_plan(root: str | Path, run_id_or_path: str) -> dict[str, Any]:
    run = read_bridge_run(root, run_id_or_path)["run"]
    return {
        "ok": True,
        "schema": "question_research_bridge_retry_plan.v1",
        "root": str(Path(root)),
        "source_run_id": run.get("id", ""),
        "tool": run.get("tool", ""),
        "action": run.get("action", ""),
        "request": run.get("request", {}),
        "command": run.get("command", ""),
        "endpoint": run.get("endpoint", ""),
        "status": "planned",
        "execute": False,
        "human_review_required": bool(run.get("human_review_required")),
        "recovery_hint": run.get("recovery_hint") or "Review the failed run artifact, then rerun the matching bridge command explicitly.",
        "artifact_paths": [run.get("path", "")] if run.get("path") else [],
    }


def _run_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for run_dir in (root / "state" / "tool-runs", root / "tool-runs"):
        if run_dir.exists():
            paths.extend(run_dir.glob("*.json"))
            paths.extend(run_dir.glob("*/result.json"))
    return sorted(set(paths), key=lambda path: path.stat().st_mtime, reverse=True)


def _normalize_run(path: Path, root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") == BRIDGE_RUN_SCHEMA:
        row = dict(data)
        row.setdefault("path", str(path))
        row.setdefault("kind", row.get("action", ""))
        row.setdefault("counts", row.get("imported_counts", {}))
        row.setdefault("result_paths", row.get("artifact_paths", []))
        row.setdefault("query_or_url", _query_or_url(row))
        return row
    tool = _tool_from_legacy(data)
    action = _action_from_legacy(path, data)
    status = _status_from_legacy(data)
    run_id = data.get("id") or (path.parent.name if path.name == "result.json" else path.stem)
    row = {
        "ok": status not in {"failed", "needs_human"},
        "schema": BRIDGE_RUN_SCHEMA,
        "id": str(run_id),
        "root": str(root),
        "tool": tool,
        "action": action,
        "request": data.get("request") if isinstance(data.get("request"), dict) else {},
        "command": data.get("command") or "",
        "endpoint": data.get("endpoint") or data.get("base_url") or "",
        "status": status,
        "artifact_paths": _artifact_paths(data, path),
        "imported_counts": _imported_counts(data),
        "error": str(data.get("error") or _response_error(data) or ""),
        "recovery_hint": str(data.get("recovery_hint") or data.get("suggested_recovery") or data.get("next_action") or ""),
        "human_review_required": _human_required(data, status),
        "response": data.get("response") if isinstance(data.get("response"), dict) else {},
        "created_at": str(data.get("created_at") or data.get("last_checked") or ""),
        "run_dir": str(path.parent),
        "path": str(path),
    }
    row["kind"] = row["action"]
    row["counts"] = row["imported_counts"]
    row["result_paths"] = row["artifact_paths"]
    row["query_or_url"] = _query_or_url(row)
    return row


def _tool_from_legacy(data: dict[str, Any]) -> str:
    if data.get("tool"):
        return str(data["tool"])
    if data.get("tool_id"):
        return str(data["tool_id"])
    if data.get("source") in {"ai-research-workflow", "web-content-fetcher", "video-knowledge-pipeline"}:
        return str(data["source"])
    plan = data.get("plan")
    if isinstance(plan, dict) and plan.get("tool"):
        return str(plan["tool"])
    return str(data.get("source") or "unknown")


def _action_from_legacy(path: Path, data: dict[str, Any]) -> str:
    if data.get("action"):
        return str(data["action"])
    if "candidate_evidence" in data and _tool_from_legacy(data) == "web-content-fetcher":
        return "fetch_source_content"
    if "imported" in data or "imported_sources" in data:
        return "import"
    return path.stem.rsplit("-", 6)[0] if "-" in path.stem else path.stem


def _status_from_legacy(data: dict[str, Any]) -> str:
    if data.get("status") in VALID_BRIDGE_STATUSES:
        return str(data["status"])
    if data.get("error") or _response_error(data) or data.get("ok") is False:
        return "failed"
    if data.get("imported") or data.get("imported_sources") or data.get("source_id") or data.get("candidate_evidence"):
        return "imported"
    if data.get("executed") is False or data.get("dry_run"):
        return "planned"
    return "succeeded"


def _artifact_paths(data: dict[str, Any], path: Path) -> list[str]:
    values = [str(path)]
    for key in ("result_path", "markdown_path", "json_path", "import_path", "manifest_path", "note_path", "stdout_path", "stderr_path"):
        if data.get(key):
            values.append(str(data[key]))
    for value in data.get("artifact_paths", []) if isinstance(data.get("artifact_paths"), list) else []:
        values.append(str(value))
    imported = data.get("imported")
    if isinstance(imported, dict) and imported.get("import_path"):
        values.append(str(imported["import_path"]))
    return sorted(set(value for value in values if value))


def _imported_counts(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("imported_counts"), dict):
        return data["imported_counts"]
    if isinstance(data.get("counts"), dict):
        return data["counts"]
    imported = data.get("imported")
    if isinstance(imported, dict) and isinstance(imported.get("counts"), dict):
        return imported["counts"]
    candidate = data.get("candidate_evidence")
    if isinstance(candidate, list):
        return {"candidate_evidence": len(candidate)}
    return {}


def _response_error(data: dict[str, Any]) -> str:
    response = data.get("response")
    return str(response.get("error") or "") if isinstance(response, dict) else ""


def _query_or_url(data: dict[str, Any]) -> str:
    request = data.get("request") if isinstance(data.get("request"), dict) else {}
    response = data.get("response") if isinstance(data.get("response"), dict) else {}
    plan = response.get("plan") if isinstance(response.get("plan"), dict) else {}
    return str(request.get("url") or request.get("topic") or request.get("query") or plan.get("query") or plan.get("url") or "")


def _human_required(data: dict[str, Any], status: str) -> bool:
    return bool(data.get("human_review_required") or data.get("requires_human_confirmation") or status in {"imported", "needs_human"})


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(rows)}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-") or "bridge"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
