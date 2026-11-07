from __future__ import annotations

from pathlib import Path
from typing import Any

from .bridge_runs import create_bridge_run
from .models import dataclass_to_dict, new_id, now_iso, project_paths
from .orchestrator import add_evidence, add_source
from .storage import ensure_project_dirs, write_json


def import_video_knowledge_artifacts(
    root: str | Path,
    bundle_dir: str | Path,
    *,
    title: str = "",
    claim_id: str = "",
    source_quality: str = "unknown",
) -> dict[str, Any]:
    project_paths(root)
    paths = ensure_project_dirs(root)
    bundle = Path(bundle_dir).expanduser()
    exports_dir = bundle / "exports" if (bundle / "exports").exists() else bundle.parent / "exports"
    review_html = bundle / "review.html"
    knowledge_note = exports_dir / "knowledge-note.md"
    full_transcript = exports_dir / "full-transcript.md"
    source_title = title or _guess_title(bundle)
    notes = "\n".join(
        [
            "Imported from video-knowledge-pipeline review bundle.",
            f"review_html: {review_html}",
            f"knowledge_note: {knowledge_note}",
            f"full_transcript: {full_transcript}",
            "Status: candidate source; requires human source-quality review.",
        ]
    )
    source = add_source(
        root,
        title=source_title,
        path=str(knowledge_note if knowledge_note.exists() else bundle),
        source_type="video_knowledge",
        quality=source_quality,
        notes=notes,
    )
    evidence = None
    if claim_id:
        quote = _candidate_quote(knowledge_note, full_transcript)
        evidence = add_evidence(
            root,
            claim_id=claim_id,
            source_id=source.id,
            quote_or_note=quote,
            relation="unknown",
            confidence="low",
            notes=f"Candidate evidence imported from video knowledge bundle; review before using. review_html: {review_html}",
        )
    manifest = {
        "schema": "question_research_video_knowledge_import.v1",
        "id": new_id("video_import"),
        "imported_at": now_iso(),
        "bundle_dir": str(bundle),
        "source_id": source.id,
        "claim_id": claim_id,
        "evidence_id": evidence.id if evidence else "",
        "artifacts": {
            "review_html": {"path": str(review_html), "exists": review_html.exists()},
            "knowledge_note": {"path": str(knowledge_note), "exists": knowledge_note.exists()},
            "full_transcript": {"path": str(full_transcript), "exists": full_transcript.exists()},
        },
        "human_review_required": True,
        "review_boundary": [
            "Imported source quality remains unknown unless explicitly provided.",
            "Imported evidence remains candidate and relation unknown.",
            "Do not treat video extraction as verified research evidence until human review is complete.",
        ],
    }
    manifest_path = paths["root"] / f"{manifest['id']}.json"
    note_path = paths["notes"] / f"{manifest['id']}.md"
    write_json(manifest_path, manifest)
    note_path.write_text(_render_import_note(source_title, manifest), encoding="utf-8")
    bridge_run = create_bridge_run(
        root,
        tool="video-knowledge-pipeline",
        action="import_video_knowledge_artifacts",
        request={"bundle_dir": str(bundle), "title": source_title, "claim_id": claim_id},
        status="imported",
        artifact_paths=[str(manifest_path), str(note_path), str(review_html), str(knowledge_note), str(full_transcript)],
        imported_counts={"sources": 1, "evidence": 1 if evidence else 0},
        human_review_required=True,
        response={"artifacts": manifest["artifacts"], "source_id": source.id, "evidence_id": evidence.id if evidence else ""},
    )
    return {
        "ok": True,
        "source": dataclass_to_dict(source),
        "evidence": dataclass_to_dict(evidence) if evidence else None,
        "manifest_path": str(manifest_path),
        "note_path": str(note_path),
        "artifacts": manifest["artifacts"],
        "human_review_required": True,
        "bridge_run": bridge_run,
        "next_actions": [
            "在 review_html 中人工复核视频知识提取结果。",
            "标注该视频知识来源质量 good/mixed/poor。",
            "如生成了候选证据，人工确认 relation/confidence 后再标为 verified。",
        ],
    }


def _guess_title(bundle: Path) -> str:
    stem = bundle.parent.name if bundle.name == "webui-bundle" else bundle.name
    return stem or "Video knowledge bundle"


def _candidate_quote(knowledge_note: Path, full_transcript: Path) -> str:
    source = knowledge_note if knowledge_note.exists() else full_transcript
    if not source.exists():
        return "Video knowledge bundle imported, but no readable knowledge note or transcript was found."
    lines = []
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("---"):
            lines.append(clean)
        if len("\n".join(lines)) >= 800:
            break
    return "\n".join(lines)[:1200] or f"Readable artifact exists: {source}"


def _render_import_note(title: str, manifest: dict[str, Any]) -> str:
    artifacts = manifest["artifacts"]
    return "\n".join(
        [
            "---",
            "type: note",
            f'title: "{title} - 视频知识包导入记录"',
            "tags: [ai-research, video-knowledge, review-required]",
            "status: candidate",
            f"created: {manifest['imported_at']}",
            "---",
            "",
            f"# 视频知识包导入记录：{title}",
            "",
            f"- Source ID：`{manifest['source_id']}`",
            f"- Evidence ID：`{manifest['evidence_id'] or '未生成'}`",
            f"- Bundle：`{manifest['bundle_dir']}`",
            f"- Review HTML：`{artifacts['review_html']['path']}`",
            f"- Knowledge note：`{artifacts['knowledge_note']['path']}`",
            f"- Full transcript：`{artifacts['full_transcript']['path']}`",
            "",
            "## 审核边界",
            "",
            "- 这是候选材料，不是已验证证据。",
            "- 来源质量需要人工标注。",
            "- 候选证据必须人工确认 relation/confidence 后才可标为 verified。",
            "",
        ]
    )
