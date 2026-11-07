from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import ClaimRecord, EvidenceRecord, ResearchProject, SourceRecord, SourceReview, dataclass_to_dict, new_id, now_iso, project_paths
from .runtime_paths import video_knowledge_root
from .storage import append_jsonl, ensure_project_dirs, load_project, mutate_jsonl, read_jsonl, rewrite_jsonl, save_project, write_json


def init_project(root: str | Path, question: str) -> ResearchProject:
    project = ResearchProject(id=new_id("research"), question=question, created_at=now_iso())
    save_project(root, project)
    return project


def add_source(
    root: str | Path,
    *,
    title: str,
    url: str = "",
    path: str = "",
    source_type: str = "web",
    quality: str = "unknown",
    notes: str = "",
) -> SourceRecord:
    paths = ensure_project_dirs(root)
    source = SourceRecord(
        id=new_id("source"),
        source_type=source_type,
        title=title,
        url=url,
        path=path,
        quality=quality,
        notes=notes,
    )
    append_jsonl(paths["sources"], [dataclass_to_dict(source)])
    return source


def add_video(
    root: str | Path,
    video_path: str | Path,
    *,
    topic: str,
    transcript_path: str | Path | None = None,
    sample_interval: float = 5.0,
    max_frames: int = 120,
    detect_scenes: bool = True,
    extract_frames: bool = True,
) -> dict[str, Any]:
    """Compatibility interface: register a video source without processing it.

    Video ASR/frame/OCR/multimodal work now belongs to video-knowledge-pipeline.
    The legacy parameters are accepted so old callers do not crash.
    """
    del sample_interval, max_frames, detect_scenes, extract_frames
    delegated_root = video_knowledge_root()
    notes = f"Video processing is delegated to {delegated_root}."
    if transcript_path:
        notes += f" Transcript hint: {transcript_path}"
    source = add_source(root, title=topic, path=str(video_path), source_type="video", notes=notes)
    return {
        "source_id": source.id,
        "video_path": str(video_path),
        "topic": topic,
        "delegated_to": str(delegated_root),
        "next_command": str(delegated_root / "scripts" / "video-knowledge.ps1") + " --help",
    }


def review_source(root: str | Path, *, source_id: str, quality: str, reason: str = "", reviewer: str = "human") -> SourceReview:
    if quality not in {"good", "mixed", "poor", "unknown"}:
        raise ValueError("quality must be good, mixed, poor, or unknown")
    paths = ensure_project_dirs(root)
    def update_source(sources: list[dict[str, Any]]) -> None:
        for source in sources:
            if source.get("id") == source_id:
                source["quality"] = quality
                source["quality_reason"] = reason
                return
        raise ValueError("source not found")

    mutate_jsonl(paths["sources"], update_source)
    review = SourceReview(id=new_id("source_review"), source_id=source_id, quality=quality, reason=reason, reviewer=reviewer)
    append_jsonl(paths["source_reviews"], [dataclass_to_dict(review)])
    append_jsonl(paths["reviews"], [{"kind": "source", "source_id": source_id, "quality": quality, "note": reason, "reviewer": reviewer, "reviewed_at": now_iso()}])
    return review


def add_claim(root: str | Path, *, text: str, notes: str = "") -> ClaimRecord:
    paths = ensure_project_dirs(root)
    claim = ClaimRecord(id=new_id("claim"), text=text, notes=notes)
    append_jsonl(paths["claims"], [dataclass_to_dict(claim)])
    append_jsonl(paths["graph"], [_graph_edge(f"question:{load_project(root).question}", f"claim:{claim.id}", "raises_claim", "manual claim added")])
    return claim


def add_evidence(
    root: str | Path,
    *,
    claim_id: str,
    source_id: str,
    quote_or_note: str,
    relation: str = "unknown",
    confidence: str = "unknown",
    notes: str = "",
) -> EvidenceRecord:
    if relation not in {"supports", "contradicts", "context", "unknown"}:
        raise ValueError("relation must be supports, contradicts, context, or unknown")
    paths = ensure_project_dirs(root)
    _require_record(paths["claims"], claim_id, "claim")
    _require_record(paths["sources"], source_id, "source")
    evidence = EvidenceRecord(
        id=new_id("evidence"),
        claim_id=claim_id,
        source_id=source_id,
        quote_or_note=quote_or_note,
        relation=relation,
        confidence=confidence,
        notes=notes,
    )
    row = dataclass_to_dict(evidence)
    append_jsonl(paths["evidence"], [row])
    append_jsonl(
        paths["graph"],
        [
            _graph_edge(f"source:{source_id}", f"evidence:{evidence.id}", "contains_evidence", relation, source_id),
            _graph_edge(f"evidence:{evidence.id}", f"claim:{claim_id}", relation, "manual evidence link", source_id),
        ],
    )
    (paths["notes"] / f"{evidence.id}-evidence-card.md").write_text(render_evidence_card(root, row), encoding="utf-8")
    return evidence


def review_evidence(
    root: str | Path,
    *,
    evidence_id: str,
    status: str,
    relation: str | None = None,
    confidence: str | None = None,
    notes: str = "",
    reviewer: str = "human",
) -> dict[str, Any]:
    if status not in {"candidate", "verified", "rejected"}:
        raise ValueError("status must be candidate, verified, or rejected")
    if relation is not None and relation not in {"supports", "contradicts", "context", "unknown"}:
        raise ValueError("relation must be supports, contradicts, context, or unknown")
    paths = ensure_project_dirs(root)
    reviewed_at = now_iso()

    def update_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
        for row in rows:
            if row.get("id") == evidence_id:
                row["status"] = status
                row["reviewed_at"] = reviewed_at
                if relation is not None:
                    row["relation"] = relation
                if confidence is not None:
                    row["confidence"] = confidence
                if notes:
                    row["review_note"] = notes
                return dict(row)
        raise ValueError("evidence not found")

    updated = mutate_jsonl(paths["evidence"], update_evidence)
    append_jsonl(paths["reviews"], [{"kind": "evidence", "evidence_id": evidence_id, "status": status, "note": notes, "reviewer": reviewer, "reviewed_at": reviewed_at}])
    (paths["notes"] / f"{evidence_id}-evidence-card.md").write_text(render_evidence_card(root, updated), encoding="utf-8")
    return {"updated": 1, "evidence": updated}


def review_graph_edge(root: str | Path, *, from_id: str, to_id: str, status: str, note: str = "") -> dict[str, Any]:
    if status not in {"candidate", "verified", "rejected"}:
        raise ValueError("status must be candidate, verified, or rejected")
    paths = ensure_project_dirs(root)
    reviewed_at = now_iso()

    def update_graph(rows: list[dict[str, Any]]) -> int:
        updated = 0
        for row in rows:
            if row.get("from_id") == from_id and row.get("to_id") == to_id:
                row["status"] = status
                row["review_note"] = note
                row["reviewed_at"] = reviewed_at
                updated += 1
        if not updated:
            raise ValueError("graph edge not found")
        return updated

    updated = mutate_jsonl(paths["graph"], update_graph)
    review = {"from_id": from_id, "to_id": to_id, "status": status, "note": note, "reviewed_at": reviewed_at}
    append_jsonl(paths["reviews"], [review])
    return {"updated": updated, "review": review}


def list_records(root: str | Path, kind: str) -> list[dict[str, Any]]:
    paths = project_paths(root)
    mapping = {
        "sources": paths["sources"],
        "claims": paths["claims"],
        "evidence": paths["evidence"],
        "graph": paths["graph"],
        "reviews": paths["reviews"],
    }
    if kind not in mapping:
        raise ValueError("kind must be sources, claims, evidence, graph, or reviews")
    return read_jsonl(mapping[kind])


def import_sources(root: str | Path, import_path: str | Path, *, default_quality: str = "unknown") -> dict[str, Any]:
    imported = []
    for row in _load_source_import_rows(import_path):
        source = add_source(
            root,
            title=str(row.get("title") or row.get("name") or row.get("url") or row.get("path") or "Untitled source"),
            url=str(row.get("url") or row.get("link") or ""),
            path=str(row.get("path") or ""),
            source_type=str(row.get("source_type") or row.get("type") or "web"),
            quality=str(row.get("quality") or default_quality),
            notes=str(row.get("notes") or row.get("snippet") or row.get("summary") or ""),
        )
        imported.append(dataclass_to_dict(source))
    return {"imported_count": len(imported), "sources": imported}


def draft_answer(root: str | Path, *, include_candidate: bool = False) -> str:
    paths = project_paths(root)
    project = load_project(root)
    claims = read_jsonl(paths["claims"])
    evidence_rows = read_jsonl(paths["evidence"])
    sources = {source.get("id"): source for source in read_jsonl(paths["sources"])}
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for evidence in evidence_rows:
        if include_candidate or evidence.get("status") == "verified":
            evidence_by_claim.setdefault(str(evidence.get("claim_id", "")), []).append(evidence)

    lines = [
        "---",
        "type: note",
        f'title: "{project.question} - 阶段性回答草稿"',
        "tags: [ai-research, answer-draft]",
        "status: active",
        f"created: {now_iso()}",
        "---",
        "",
        f"# 阶段性回答草稿：{project.question}",
        "",
        "> 这不是最终结论。它只汇总当前已审核证据，并保留反证、上下文和缺口。",
        "",
    ]
    for claim in claims:
        claim_id = str(claim.get("id", ""))
        lines.extend([f"## {claim.get('text', '')}", "", f"- 主张 ID：`{claim_id}`"])
        items = evidence_by_claim.get(claim_id, [])
        if not items:
            lines.extend(["- 当前没有已纳入的证据。", ""])
            continue
        for evidence in items:
            source = sources.get(evidence.get("source_id"), {})
            lines.extend(
                [
                    f"- `{evidence.get('relation', 'unknown')}` / `{evidence.get('confidence', 'unknown')}` / 来源质量 `{source.get('quality', 'unknown')}`",
                    f"  - 来源：{source.get('title', evidence.get('source_id', ''))}",
                    f"  - 摘录：{evidence.get('quote_or_note', '')}",
                ]
            )
        lines.append("")
    if not claims:
        lines.append("- 暂无主张")
    return "\n".join(lines).rstrip() + "\n"


def export_obsidian(root: str | Path, vault: str | Path, folder: str = "00_Inbox/AI/问题导向研究流程POC") -> dict[str, Any]:
    paths = project_paths(root)
    output_dir = Path(vault) / _safe_relative_folder(folder)
    output_dir.mkdir(parents=True, exist_ok=True)
    overview_path = paths["notes"] / "research-project-overview.md"
    answer_path = paths["notes"] / "answer-draft.md"
    overview_path.write_text(render_project_overview(root), encoding="utf-8")
    answer_path.write_text(draft_answer(root), encoding="utf-8")
    exported = []
    for note in sorted(paths["notes"].glob("*.md")):
        target = output_dir / note.name
        target.write_text(note.read_text(encoding="utf-8"), encoding="utf-8")
        exported.append(str(target))
    return {"exported": exported, "folder": str(output_dir)}


def write_graph_csv(root: str | Path) -> Path:
    paths = project_paths(root)
    target = paths["root"] / "graph-candidates.csv"
    fieldnames = ["from_id", "to_id", "edge_type", "status", "reason", "source_ref", "review_note", "reviewed_at"]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in read_jsonl(paths["graph"]):
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return target


def render_project_overview(root: str | Path) -> str:
    paths = project_paths(root)
    project = load_project(root)
    sources = read_jsonl(paths["sources"])
    claims = read_jsonl(paths["claims"])
    evidence = read_jsonl(paths["evidence"])
    graph_rows = read_jsonl(paths["graph"])
    lines = [
        "---",
        "type: note",
        f'title: "{project.question}"',
        "tags: [ai-research, question-led-research]",
        "status: active",
        f"created: {now_iso()}",
        "---",
        "",
        f"# 研究项目总览：{project.question}",
        "",
        f"- 项目 ID：`{project.id}`",
        f"- 状态：`{project.status}`",
        f"- 来源数量：{len(sources)}",
        f"- 主张数量：{len(claims)}",
        f"- 证据数量：{len(evidence)}",
        f"- 图谱候选边：{len(graph_rows)}",
        "",
        "## 来源清单",
        "",
    ]
    lines.extend(f"- `{source.get('quality', 'unknown')}` {source.get('title', '')}" for source in sources) if sources else lines.append("- 暂无来源")
    lines.extend(["", "## 主张清单", ""])
    lines.extend(f"- `{claim.get('status', 'open')}` {claim.get('text', '')} (`{claim.get('id', '')}`)" for claim in claims) if claims else lines.append("- 暂无主张")
    return "\n".join(lines).rstrip() + "\n"


def render_evidence_card(root: str | Path, evidence: dict[str, Any]) -> str:
    project = load_project(root)
    return "\n".join(
        [
            "---",
            "type: note",
            f'title: "{evidence.get("id", "evidence")} evidence card"',
            "tags: [ai-research, evidence]",
            "status: active",
            f"created: {now_iso()}",
            "---",
            "",
            f"# 证据卡：{evidence.get('id', '')}",
            "",
            f"- 研究问题：{project.question}",
            f"- 主张 ID：`{evidence.get('claim_id', '')}`",
            f"- 来源 ID：`{evidence.get('source_id', '')}`",
            f"- 关系：`{evidence.get('relation', 'unknown')}`",
            f"- 置信度：`{evidence.get('confidence', 'unknown')}`",
            f"- 状态：`{evidence.get('status', 'candidate')}`",
            "",
            "## 摘录 / 说明",
            "",
            str(evidence.get("quote_or_note", "")),
            "",
        ]
    )


def _graph_edge(from_id: str, to_id: str, edge_type: str, reason: str, source_ref: str = "") -> dict[str, str]:
    return {
        "from_id": from_id,
        "to_id": to_id,
        "edge_type": edge_type,
        "status": "candidate",
        "reason": reason,
        "source_ref": source_ref,
        "review_note": "",
        "reviewed_at": "",
    }


def _require_record(path: Path, record_id: str, label: str) -> None:
    if not any(row.get("id") == record_id for row in read_jsonl(path)):
        raise ValueError(f"{label} not found: {record_id}")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    rewrite_jsonl(path, rows)


def _load_source_import_rows(import_path: str | Path) -> list[dict[str, Any]]:
    path = Path(import_path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("sources"), list):
        return data["sources"]
    raise ValueError("source import must be a JSON array, JSONL file, or object with sources[]")


def _safe_relative_folder(folder: str) -> Path:
    target = Path(folder)
    if target.is_absolute() or ".." in target.parts:
        raise ValueError("folder must be a safe relative path")
    return target
