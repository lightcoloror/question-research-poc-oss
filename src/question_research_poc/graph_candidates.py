from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import now_iso, project_paths
from .orchestrator import list_records
from .storage import append_jsonl, load_project, read_jsonl, write_json


GRAPH_CANDIDATE_SCHEMA = "question_research_graph_candidates.v1"
GRAPH_EXPORT_SCHEMA = "question_research_reviewed_graph_export.v1"
REVIEWABLE_STATUSES = {"candidate", "accepted", "verified", "rejected"}


def generate_graph_candidates(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    project = load_project(project_root)
    existing = _read_edges(project_root)
    existing_keys = {_edge_key(edge) for edge in existing}
    sources = {str(source.get("id", "")): source for source in list_records(project_root, "sources")}
    claims = list_records(project_root, "claims")
    evidence = list_records(project_root, "evidence")
    new_edges: list[dict[str, Any]] = []

    for claim in claims:
        edge = _edge(
            f"question:{project.id}",
            f"claim:{claim.get('id', '')}",
            "question_to_claim",
            "claim",
            "Claim belongs to the current research question.",
            evidence_ref=str(claim.get("id", "")),
        )
        _append_unique(edge, existing_keys, new_edges)

    for item in evidence:
        source_id = str(item.get("source_id", ""))
        claim_id = str(item.get("claim_id", ""))
        source = sources.get(source_id, {})
        _append_unique(
            _edge(
                f"source:{source_id}",
                f"evidence:{item.get('id', '')}",
                "source_contains_evidence",
                "evidence",
                "Source contains this evidence card.",
                source_ref=source_id,
                evidence_ref=str(item.get("id", "")),
            ),
            existing_keys,
            new_edges,
        )
        _append_unique(
            _edge(
                f"evidence:{item.get('id', '')}",
                f"claim:{claim_id}",
                str(item.get("relation") or "related_to"),
                "claim_evidence",
                "Evidence is linked to this claim.",
                source_ref=source_id,
                evidence_ref=str(item.get("id", "")),
            ),
            existing_keys,
            new_edges,
        )
        if source:
            _append_unique(
                _edge(
                    f"source:{source_id}",
                    f"claim:{claim_id}",
                    "source_informs_claim",
                    "source_claim",
                    f"Source '{source.get('title', source_id)}' informs this claim through evidence.",
                    source_ref=source_id,
                    evidence_ref=str(item.get("id", "")),
                ),
                existing_keys,
                new_edges,
            )

    if new_edges:
        append_jsonl(project_paths(project_root)["graph"], new_edges)
    return _payload(project_root, added=new_edges)


def list_graph_candidates(root: str | Path, *, status: str | None = None, edge_type: str | None = None) -> dict[str, Any]:
    project_root = Path(root)
    rows = _read_edges(project_root)
    if status:
        rows = [row for row in rows if _status(row) == status]
    if edge_type:
        rows = [row for row in rows if str(row.get("edge_type", "")) == edge_type]
    return {
        "ok": True,
        "schema": GRAPH_CANDIDATE_SCHEMA,
        "root": str(project_root),
        "path": str(project_paths(project_root)["graph"]),
        "candidates": rows,
        "counts": _counts(rows),
        "human_review_required": any(_status(row) == "candidate" for row in rows),
    }


def review_graph_candidate(root: str | Path, *, from_id: str, to_id: str, status: str, note: str = "", reviewer: str = "human") -> dict[str, Any]:
    if status not in {"candidate", "accepted", "rejected", "verified"}:
        raise ValueError("status must be candidate, accepted, verified, or rejected")
    project_root = Path(root)
    path = project_paths(project_root)["graph"]
    rows = _read_edges(project_root)
    reviewed_at = now_iso()
    updated = 0
    for row in rows:
        if row.get("from_id") == from_id and row.get("to_id") == to_id:
            row["status"] = status
            row["review_note"] = note
            row["reviewer"] = reviewer
            row["reviewed_at"] = reviewed_at
            row["human_review_required"] = status == "candidate"
            updated += 1
    if not updated:
        raise ValueError("graph candidate not found")
    _write_jsonl(path, rows)
    return {"ok": True, "updated": updated, "review": {"from_id": from_id, "to_id": to_id, "status": status, "note": note, "reviewer": reviewer, "reviewed_at": reviewed_at}}


def export_reviewed_graph(root: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root)
    out_dir = Path(output_dir) if output_dir else project_root / "exports" / "reviewed-graph"
    out_dir.mkdir(parents=True, exist_ok=True)
    accepted = [edge for edge in _read_edges(project_root) if _status(edge) in {"accepted", "verified"}]
    payload = {"ok": True, "schema": GRAPH_EXPORT_SCHEMA, "root": str(project_root), "edges": accepted, "counts": _counts(accepted), "human_review_required": False}
    json_path = out_dir / "reviewed-graph.json"
    md_path = out_dir / "reviewed-graph.md"
    write_json(json_path, payload)
    md_path.write_text(_render_markdown(project_root, accepted), encoding="utf-8")
    return {**payload, "output_dir": str(out_dir), "files": {"json": str(json_path), "markdown": str(md_path)}}


def _payload(project_root: Path, *, added: list[dict[str, Any]]) -> dict[str, Any]:
    listed = list_graph_candidates(project_root)
    return {**listed, "added": added, "added_count": len(added)}


def _edge(from_id: str, to_id: str, edge_type: str, created_by: str, reason: str, *, source_ref: str = "", evidence_ref: str = "") -> dict[str, Any]:
    return {
        "from_id": from_id,
        "to_id": to_id,
        "edge_type": edge_type,
        "status": "candidate",
        "reason": reason,
        "source_ref": source_ref,
        "evidence_ref": evidence_ref,
        "created_by": created_by,
        "human_review_required": True,
        "created_at": now_iso(),
        "review_note": "",
        "reviewed_at": "",
    }


def _append_unique(edge: dict[str, Any], existing_keys: set[tuple[str, str, str]], new_edges: list[dict[str, Any]]) -> None:
    key = _edge_key(edge)
    if key in existing_keys:
        return
    existing_keys.add(key)
    new_edges.append(edge)


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (str(edge.get("from_id", "")), str(edge.get("to_id", "")), str(edge.get("edge_type", "")))


def _status(edge: dict[str, Any]) -> str:
    status = str(edge.get("status") or "candidate")
    return status if status in REVIEWABLE_STATUSES else "candidate"


def _read_edges(root: Path) -> list[dict[str, Any]]:
    return [_normalize_edge(row) for row in read_jsonl(project_paths(root)["graph"])]


def _normalize_edge(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized.setdefault("created_by", "legacy_orchestrator")
    normalized.setdefault("evidence_ref", str(normalized.get("source_ref", "")))
    normalized.setdefault("human_review_required", _status(normalized) == "candidate")
    normalized.setdefault("review_note", "")
    normalized.setdefault("reviewed_at", "")
    return normalized


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(rows), "candidate": 0, "accepted": 0, "verified": 0, "rejected": 0}
    for row in rows:
        counts[_status(row)] = counts.get(_status(row), 0) + 1
    return counts


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _render_markdown(root: Path, edges: list[dict[str, Any]]) -> str:
    project = load_project(root)
    lines = [f"# Reviewed Graph: {project.question}", "", f"- Accepted edges: {len(edges)}", ""]
    if not edges:
        lines.append("- No accepted graph edges yet.")
    for edge in edges:
        lines.append(f"- `{edge.get('edge_type', '')}` {edge.get('from_id', '')} -> {edge.get('to_id', '')}")
        if edge.get("reason"):
            lines.append(f"  - Reason: {edge.get('reason')}")
        if edge.get("evidence_ref"):
            lines.append(f"  - Evidence: `{edge.get('evidence_ref')}`")
    return "\n".join(lines).rstrip() + "\n"
