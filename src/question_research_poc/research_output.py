from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .completeness_audit import audit_research_completeness
from .models import project_paths
from .storage import load_project, read_jsonl, write_json


RESEARCH_OUTPUT_SCHEMA = "research-output.v1"
RESEARCH_OUTPUT_SCHEMA_VERSION = "1.0.0"
RESEARCH_OUTPUT_FILENAME = "research-output.v1.json"
_NOTE_KEYS = {
    "archive_path",
    "artifact_sha256",
    "content_hash",
    "extracted_path",
    "fetched_at",
    "freshness",
    "full_transcript",
    "image_path",
    "knowledge_note",
    "local_path",
    "markdown_path",
    "observed_at",
    "published_at",
    "publisher",
    "retrieved_at",
    "review_html",
    "screenshot_path",
    "source_path",
    "verification_status",
}
_MEDIA_SUFFIXES = {".aac", ".flac", ".gif", ".jpeg", ".jpg", ".m4a", ".mov", ".mp3", ".mp4", ".png", ".wav", ".webm", ".webp"}


def research_output_schema_path() -> Path:
    source_tree_schema = Path(__file__).resolve().parents[2] / "schemas" / "research-output.v1.schema.json"
    if source_tree_schema.is_file():
        return source_tree_schema
    return Path(__file__).resolve().parent / "schemas" / "research-output.v1.schema.json"


def build_research_output(
    root: str | Path,
    *,
    scope: str = "",
    audience: str = "general",
    requested_outputs: Iterable[str] | None = None,
    scope_constraints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Adapt one existing QRP project into the canonical content handoff contract."""
    project_root = Path(root)
    paths = project_paths(project_root)
    project = load_project(project_root)
    sources_raw = _sorted_records(read_jsonl(paths["sources"]))
    source_reviews = _sorted_records(read_jsonl(paths["source_reviews"]))
    claims_raw = _sorted_records(read_jsonl(paths["claims"]))
    evidence_raw = _sorted_records(read_jsonl(paths["evidence"]))
    reviews_raw = sorted(read_jsonl(paths["reviews"]), key=_review_sort_key)
    audit = audit_research_completeness(project_root)

    source_review_ids: dict[str, list[str]] = {}
    for review in source_reviews:
        source_review_ids.setdefault(str(review.get("source_id") or ""), []).append(str(review.get("id") or ""))
    review_events = _review_events(reviews_raw)
    evidence_review_ids = {
        event["target_id"] for event in review_events if event["kind"] == "evidence"
    }

    sources = [
        _source_output(project_root, source, source_review_ids.get(str(source.get("id") or ""), []))
        for source in sources_raw
    ]
    source_ids = {item["source_id"] for item in sources}
    evidence = [_evidence_output(item, evidence_review_ids) for item in evidence_raw]
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    evidence_links = [
        {
            "evidence_id": item["evidence_id"],
            "claim_id": item["claim_id"],
            "source_id": item["source_id"],
            "relation": item["relation"],
            "evidence_status": item["evidence_status"],
        }
        for item in evidence
    ]
    claims = [_claim_output(claim, evidence) for claim in claims_raw]
    claim_ids = {item["claim_id"] for item in claims}
    contradictions = [
        {
            "claim_id": item["claim_id"],
            "evidence_id": item["evidence_id"],
            "source_id": item["source_id"],
            "evidence_status": item["evidence_status"],
            "resolution_status": _contradiction_resolution(item["evidence_status"]),
        }
        for item in evidence
        if item["relation"] == "contradicts"
    ]

    unknowns = _unknowns(
        audit,
        sources,
        evidence,
        claim_ids=claim_ids,
        source_ids=source_ids,
    )
    custom_blockers = sorted({item["code"] for item in unknowns if item["severity"] == "blocker"})
    custom_warnings = [item["message"] for item in unknowns if item["severity"] == "warning"]
    blocking_gates = sorted(set(str(item) for item in audit.get("blocking_gates", [])) | set(custom_blockers))
    warnings = _dedupe([str(item) for item in audit.get("warnings", [])] + custom_warnings)
    ready = bool(audit.get("ready_for_answer")) and not blocking_gates

    guarded_answer = _guarded_answer(claims, evidence_by_id, ready, blocking_gates, warnings)
    evidence_summary = _evidence_summary(evidence, contradictions)
    review_summary = {
        "overall": "verified" if ready else ("reviewed" if review_events and evidence_summary["overall"] != "candidate" else "candidate"),
        "human_review_required": bool(not ready or audit.get("human_review_required")),
        "events": review_events,
    }

    outputs = _dedupe([str(item).strip() for item in (requested_outputs or ["guarded_answer", "claims", "evidence"]) if str(item).strip()])
    constraints = _dedupe([str(item).strip() for item in (scope_constraints or []) if str(item).strip()])
    source_systems = _source_systems(sources_raw)
    return {
        "schema": RESEARCH_OUTPUT_SCHEMA,
        "schema_version": RESEARCH_OUTPUT_SCHEMA_VERSION,
        "research_id": project.id,
        "question": project.question,
        "scope": {
            "statement": scope or project.notes or "",
            "constraints": constraints,
        },
        "audience": audience or "general",
        "requested_outputs": outputs or ["guarded_answer"],
        "sources": sources,
        "claims": claims,
        "evidence": evidence,
        "evidence_links": evidence_links,
        "contradictions": contradictions,
        "unknowns": unknowns,
        "review_status": review_summary,
        "evidence_status": evidence_summary,
        "completeness": {
            "ready_for_answer": ready,
            "blocking_gates": blocking_gates,
            "warnings": warnings,
            "coverage": dict(audit.get("coverage") or {}),
        },
        "guarded_final_answer": guarded_answer,
        "media_refs": _media_refs(sources),
        "visual_leads": _visual_leads(sources),
        "quotable_facts": _quotable_facts(evidence),
        "provenance": {
            "input_files": _input_files(project_root, paths),
            "source_systems": source_systems,
            "offline_only": True,
            "external_api_called": False,
            "model_memory_used_as_evidence": False,
        },
        "generator": {
            "name": "question-research-poc",
            "component": "research_output",
            "version": RESEARCH_OUTPUT_SCHEMA,
        },
        "created_at": project.created_at,
    }


def validate_research_output(payload: dict[str, Any]) -> dict[str, Any]:
    schema_path = research_output_schema_path()
    try:
        import jsonschema
    except ImportError:
        return {
            "ok": False,
            "status": "validator_unavailable",
            "schema_path": str(schema_path),
            "errors": ["Install the project-local jsonschema validator to validate research-output.v1."],
        }
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        {
            "path": "/" + "/".join(str(part) for part in error.absolute_path),
            "message": error.message,
        }
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    ]
    return {
        "ok": not errors,
        "status": "pass" if not errors else "blocked",
        "schema_path": str(schema_path),
        "errors": errors,
    }


def export_research_output(
    root: str | Path,
    output_path: str | Path | None = None,
    *,
    scope: str = "",
    audience: str = "general",
    requested_outputs: Iterable[str] | None = None,
    scope_constraints: Iterable[str] | None = None,
) -> dict[str, Any]:
    project_root = Path(root)
    payload = build_research_output(
        project_root,
        scope=scope,
        audience=audience,
        requested_outputs=requested_outputs,
        scope_constraints=scope_constraints,
    )
    validation = validate_research_output(payload)
    if not validation["ok"]:
        return {
            "ok": False,
            "schema": "research-output-export-receipt.v1",
            "exported": False,
            "validation": validation,
        }
    target = Path(output_path) if output_path else project_root / "exports" / "research-output" / RESEARCH_OUTPUT_FILENAME
    write_json(target, payload)
    artifact_bytes = target.read_bytes()
    canonical_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "ok": True,
        "schema": "research-output-export-receipt.v1",
        "exported": True,
        "artifact_path": str(target),
        "schema_path": str(research_output_schema_path()),
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "payload_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "validation": validation,
        "guarded_status": payload["guarded_final_answer"]["status"],
        "ready_for_answer": payload["guarded_final_answer"]["ready"],
        "counts": {
            "sources": len(payload["sources"]),
            "claims": len(payload["claims"]),
            "evidence": len(payload["evidence"]),
            "contradictions": len(payload["contradictions"]),
            "unknowns": len(payload["unknowns"]),
        },
        "offline_only": True,
    }


def _source_output(project_root: Path, source: dict[str, Any], review_ids: list[str]) -> dict[str, Any]:
    note_fields = _parse_note_fields(source.get("notes"))
    raw_path = str(
        source.get("path")
        or note_fields.get("local_path")
        or note_fields.get("source_path")
        or note_fields.get("archive_path")
        or note_fields.get("knowledge_note")
        or note_fields.get("extracted_path")
        or note_fields.get("markdown_path")
        or ""
    ).strip()
    url = str(source.get("url") or "").strip()
    resolved_path = _resolve_local_path(project_root, raw_path)
    recorded_hash = str(note_fields.get("artifact_sha256") or note_fields.get("content_hash") or "").strip()
    computed_hash = _hash_file(resolved_path) if resolved_path and resolved_path.is_file() else ""
    if recorded_hash and computed_hash and recorded_hash.lower() != computed_hash.lower():
        hash_value, hash_status = recorded_hash, "mismatch"
    elif computed_hash:
        hash_value, hash_status = computed_hash, "verified"
    elif recorded_hash:
        hash_value, hash_status = recorded_hash, "recorded"
    else:
        hash_value, hash_status = None, "missing"
    ref_status = _ref_status(raw_path, resolved_path, url)
    source_id = str(source.get("id") or "")
    return {
        "source_id": source_id,
        "title": str(source.get("title") or ""),
        "url": url or None,
        "archive_path": _normalize_ref(raw_path) if raw_path else None,
        "source_type": str(source.get("source_type") or "unknown"),
        "publisher": note_fields.get("publisher") or None,
        "fetched_at": note_fields.get("fetched_at") or note_fields.get("retrieved_at") or None,
        "freshness": _freshness(source, note_fields),
        "hash": {"algorithm": "sha256", "value": hash_value, "status": hash_status},
        "quality": str(source.get("quality") or "unknown") if str(source.get("quality") or "unknown") in {"good", "mixed", "poor", "unknown"} else "unknown",
        "review_status": "reviewed" if review_ids else "candidate",
        "ref_status": ref_status,
        "provenance": {
            "created_at": str(source.get("created_at") or "") or None,
            "review_refs": _dedupe([item for item in review_ids if item]),
            "note_fields": note_fields,
        },
    }


def _evidence_output(item: dict[str, Any], reviewed_ids: set[str]) -> dict[str, Any]:
    notes = str(item.get("notes") or "")
    note_fields = _parse_note_fields(notes)
    evidence_id = str(item.get("id") or "")
    status = str(item.get("status") or "candidate")
    if status not in {"candidate", "verified", "rejected"}:
        status = "candidate"
    return {
        "evidence_id": evidence_id,
        "claim_id": str(item.get("claim_id") or ""),
        "source_id": str(item.get("source_id") or ""),
        "relation": str(item.get("relation") or "unknown") if str(item.get("relation") or "unknown") in {"supports", "contradicts", "context", "unknown"} else "unknown",
        "evidence_status": status,
        "review_status": "reviewed" if evidence_id in reviewed_ids or status in {"verified", "rejected"} else "candidate",
        "confidence": str(item.get("confidence") or "unknown"),
        "excerpt": _short_text(str(item.get("quote_or_note") or ""), max_words=25, max_chars=160)[0],
        "observed_at": note_fields.get("observed_at") or note_fields.get("retrieved_at") or str(item.get("reviewed_at") or item.get("created_at") or "") or None,
        "source_path": note_fields.get("source_path") or note_fields.get("local_path") or None,
        "artifact_sha256": note_fields.get("artifact_sha256") or note_fields.get("content_hash") or None,
        "ai_synthesis": _is_ai_synthesis(notes),
    }


def _claim_output(claim: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    claim_id = str(claim.get("id") or "")
    linked = [item for item in evidence if item["claim_id"] == claim_id]
    usable_verified = [item for item in linked if item["evidence_status"] == "verified" and not item["ai_synthesis"]]
    support = [item["evidence_id"] for item in linked if item["relation"] == "supports"]
    contradictions = [item["evidence_id"] for item in linked if item["relation"] == "contradicts"]
    context = [item["evidence_id"] for item in linked if item["relation"] == "context"]
    verified_support = any(item["relation"] == "supports" for item in usable_verified)
    verified_contradiction = any(item["relation"] == "contradicts" for item in usable_verified)
    candidates = any(item["evidence_status"] == "candidate" for item in linked)
    if verified_contradiction:
        evidence_status, review_status = "contradicted", "reviewed"
    elif verified_support:
        evidence_status, review_status = "verified", "verified"
    elif candidates:
        evidence_status, review_status = "candidate", "candidate"
    elif linked:
        evidence_status, review_status = "reviewed", "reviewed"
    else:
        evidence_status, review_status = "missing", "candidate"
    return {
        "claim_id": claim_id,
        "text": str(claim.get("text") or ""),
        "claim_status": str(claim.get("status") or "open"),
        "review_status": review_status,
        "evidence_status": evidence_status,
        "evidence_ids": _dedupe([item["evidence_id"] for item in linked]),
        "supporting_evidence_ids": _dedupe(support),
        "contradicting_evidence_ids": _dedupe(contradictions),
        "context_evidence_ids": _dedupe(context),
        "source_ids": _dedupe([item["source_id"] for item in linked]),
    }


def _unknowns(
    audit: dict[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    claim_ids: set[str],
    source_ids: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in audit.get("items", []):
        if not isinstance(item, dict):
            continue
        refs = item.get("records") if isinstance(item.get("records"), list) else []
        ref_id = str(refs[0].get("id") or "") if refs and isinstance(refs[0], dict) else ""
        rows.append(
            _unknown(
                str(item.get("item_type") or "audit_unknown"),
                "blocker" if item.get("severity") == "blocker" else "warning",
                str(item.get("title") or item.get("action") or "Research audit item."),
                claim_id=ref_id if ref_id in claim_ids else None,
                source_id=ref_id if ref_id in source_ids else None,
            )
        )
    for source in sources:
        source_id = source["source_id"]
        if source["ref_status"] == "missing":
            rows.append(_unknown("source_ref_missing", "blocker", "Source has no resolvable URL or local archive.", source_id=source_id))
        if source["hash"]["status"] == "missing":
            rows.append(_unknown("source_hash_missing", "warning", "Source content hash is not recorded.", source_id=source_id))
        if source["hash"]["status"] == "mismatch":
            rows.append(_unknown("source_hash_mismatch", "blocker", "Recorded source hash does not match the local archive.", source_id=source_id))
        if source["freshness"] == "unknown":
            rows.append(_unknown("source_freshness_unknown", "warning", "Source freshness has not been established.", source_id=source_id))
    for item in evidence:
        evidence_id = item["evidence_id"]
        if item["claim_id"] not in claim_ids:
            rows.append(_unknown("evidence_claim_ref_missing", "blocker", "Evidence points to a missing claim.", claim_id=item["claim_id"] or None, evidence_id=evidence_id))
        if item["source_id"] not in source_ids:
            rows.append(_unknown("evidence_source_ref_missing", "blocker", "Evidence points to a missing source.", source_id=item["source_id"] or None, evidence_id=evidence_id))
        if item["relation"] == "contradicts" and item["evidence_status"] == "verified" and not item["ai_synthesis"]:
            rows.append(_unknown("unresolved_verified_contradiction", "blocker", "Verified contradicting evidence must be resolved before a guarded final answer.", claim_id=item["claim_id"], source_id=item["source_id"], evidence_id=evidence_id))
        if item["ai_synthesis"]:
            severity = "blocker" if item["evidence_status"] == "verified" else "warning"
            rows.append(_unknown("ai_synthesis_not_fact", severity, "AI synthesis remains non-factual material even when imported or reviewed.", claim_id=item["claim_id"], source_id=item["source_id"], evidence_id=evidence_id))
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in rows:
        key = (item["code"], item["claim_id"], item["source_id"], item["evidence_id"])
        unique[key] = item
    return sorted(unique.values(), key=lambda item: (item["severity"] != "blocker", item["code"], item["claim_id"] or "", item["source_id"] or "", item["evidence_id"] or ""))


def _guarded_answer(
    claims: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    ready: bool,
    blocking_gates: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if not ready:
        return {
            "status": "blocked",
            "ready": False,
            "answer": None,
            "claim_ids": [],
            "evidence_ids": [],
            "source_ids": [],
            "blocking_gates": blocking_gates,
            "warnings": warnings,
            "guardrail": "Blocked output is not a final answer. Candidate, contradicted, or unlinked material must not be published as fact.",
        }
    deliverable = [item for item in claims if item["evidence_status"] == "verified"]
    evidence_ids: list[str] = []
    source_ids: list[str] = []
    lines: list[str] = []
    for claim in deliverable:
        verified_support = [
            evidence_by_id[evidence_id]
            for evidence_id in claim["supporting_evidence_ids"]
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id]["evidence_status"] == "verified"
            and not evidence_by_id[evidence_id]["ai_synthesis"]
        ]
        claim_evidence_ids = [item["evidence_id"] for item in verified_support]
        claim_source_ids = _dedupe([item["source_id"] for item in verified_support])
        evidence_ids.extend(claim_evidence_ids)
        source_ids.extend(claim_source_ids)
        lines.append(
            f"- {claim['text']} [claim:{claim['claim_id']}; evidence:{','.join(claim_evidence_ids)}; sources:{','.join(claim_source_ids)}]"
        )
    return {
        "status": "verified",
        "ready": True,
        "answer": "\n".join(lines),
        "claim_ids": [item["claim_id"] for item in deliverable],
        "evidence_ids": _dedupe(evidence_ids),
        "source_ids": _dedupe(source_ids),
        "blocking_gates": [],
        "warnings": warnings,
        "guardrail": "Only verified non-synthesis support evidence is included; citations remain bound to QRP claim, evidence, and source IDs.",
    }


def _evidence_summary(evidence: list[dict[str, Any]], contradictions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "candidate": sum(1 for item in evidence if item["evidence_status"] == "candidate"),
        "verified": sum(1 for item in evidence if item["evidence_status"] == "verified"),
        "rejected": sum(1 for item in evidence if item["evidence_status"] == "rejected"),
        "contradictions": sum(1 for item in contradictions if item["resolution_status"] == "unresolved"),
    }
    if counts["contradictions"]:
        overall = "contradicted"
    elif counts["candidate"]:
        overall = "candidate"
    elif not evidence:
        overall = "missing"
    elif counts["verified"]:
        overall = "verified"
    else:
        overall = "reviewed"
    return {"overall": overall, "counts": counts}


def _review_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        kind = str(row.get("kind") or "")
        if kind == "source":
            target_id = str(row.get("source_id") or "")
            decision = str(row.get("quality") or "unknown")
        elif kind == "evidence":
            target_id = str(row.get("evidence_id") or "")
            decision = str(row.get("status") or "candidate")
        else:
            continue
        events.append(
            {
                "kind": kind,
                "target_id": target_id,
                "decision": decision,
                "reviewer": str(row.get("reviewer") or "human"),
                "reviewed_at": str(row.get("reviewed_at") or "") or None,
            }
        )
    return events


def _media_refs(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for source in sources:
        source_type = source["source_type"].lower()
        archive_path = source["archive_path"] or ""
        suffix = Path(archive_path).suffix.lower() if archive_path and not archive_path.startswith("local://") else ""
        if not any(token in source_type for token in ("video", "audio", "image", "media", "podcast")) and suffix not in _MEDIA_SUFFIXES:
            continue
        refs.append(
            {
                "source_id": source["source_id"],
                "media_type": source["source_type"],
                "path": source["archive_path"],
                "url": source["url"],
                "review_status": source["review_status"],
                "ref_status": source["ref_status"],
            }
        )
    return refs


def _visual_leads(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for source in sources:
        note_fields = source["provenance"]["note_fields"]
        refs = []
        for key in ("screenshot_path", "image_path", "review_html"):
            if note_fields.get(key):
                refs.append((key, note_fields[key]))
        if not refs and any(token in source["source_type"].lower() for token in ("video", "image", "web")):
            ref = source["archive_path"] or source["url"]
            if ref:
                refs.append((source["source_type"], ref))
        for kind, ref in refs:
            leads.append(
                {
                    "source_id": source["source_id"],
                    "kind": kind,
                    "ref": _normalize_ref(ref),
                    "status": source["review_status"],
                }
            )
    return leads


def _quotable_facts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    used_sources: set[str] = set()
    for item in evidence:
        if item["source_id"] in used_sources:
            continue
        if item["evidence_status"] != "verified" or item["relation"] not in {"supports", "context"} or item["ai_synthesis"]:
            continue
        text, word_count, truncated = _short_text(item["excerpt"], max_words=25, max_chars=120)
        facts.append(
            {
                "claim_id": item["claim_id"],
                "evidence_id": item["evidence_id"],
                "source_id": item["source_id"],
                "text": text,
                "word_count": word_count,
                "truncated": truncated,
                "review_status": "verified",
            }
        )
        used_sources.add(item["source_id"])
    return facts


def _input_files(project_root: Path, paths: dict[str, Path]) -> list[dict[str, Any]]:
    keys = ("project", "sources", "source_reviews", "claims", "evidence", "reviews")
    rows = []
    for key in keys:
        path = paths[key]
        exists = path.is_file()
        try:
            relative = path.relative_to(project_root).as_posix()
        except ValueError:
            relative = _normalize_ref(str(path))
        rows.append(
            {
                "path": relative,
                "sha256": _hash_file(path) if exists else None,
                "status": "present" if exists else "missing",
            }
        )
    return rows


def _source_systems(sources: list[dict[str, Any]]) -> list[str]:
    systems = ["question-research-poc"]
    text = "\n".join(str(item.get("notes") or "").lower() for item in sources)
    if "ai-research-workflow" in text:
        systems.append("ai-research-workflow")
    if "web-content-fetcher" in text:
        systems.append("web-content-fetcher")
    if "video-knowledge-pipeline" in text or any("video" in str(item.get("source_type") or "").lower() for item in sources):
        systems.append("video-knowledge-pipeline")
    return systems


def _freshness(source: dict[str, Any], note_fields: dict[str, str]) -> str:
    explicit = str(note_fields.get("freshness") or "").lower()
    if explicit in {"current", "stale", "unknown", "not_applicable"}:
        return explicit
    source_type = str(source.get("source_type") or "").lower()
    if source_type in {"book", "local", "local_fixture", "video", "video_knowledge"}:
        return "not_applicable"
    return "unknown"


def _ref_status(raw_path: str, resolved_path: Path | None, url: str) -> str:
    if raw_path.startswith("local://"):
        return "resolved"
    if resolved_path and resolved_path.exists():
        return "resolved"
    if url:
        return "remote"
    return "missing"


def _resolve_local_path(project_root: Path, value: str) -> Path | None:
    if not value or value.startswith("local://"):
        return None
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _parse_note_fields(value: object) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in str(value or "").splitlines():
        key, separator, raw = line.partition(":")
        normalized = key.strip().lower()
        if separator and normalized in _NOTE_KEYS and raw.strip():
            fields[normalized] = raw.strip()
    return dict(sorted(fields.items()))


def _is_ai_synthesis(notes: str) -> bool:
    normalized = notes.lower()
    return any(marker in normalized for marker in ("ai synthesis", "ai-synthesis", "machine-generated synthesis", "model synthesis", "模型综合", "ai生成综合"))


def _short_text(value: str, *, max_words: int, max_chars: int) -> tuple[str, int, bool]:
    clean = re.sub(r"\s+", " ", value).strip()
    words = clean.split(" ") if clean else []
    word_limited = " ".join(words[:max_words])
    limited = word_limited[:max_chars].rstrip()
    truncated = limited != clean
    return limited, min(len(words), max_words), truncated


def _unknown(
    code: str,
    severity: str,
    message: str,
    *,
    claim_id: str | None = None,
    source_id: str | None = None,
    evidence_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "claim_id": claim_id,
        "source_id": source_id,
        "evidence_id": evidence_id,
    }


def _contradiction_resolution(status: str) -> str:
    if status == "verified":
        return "unresolved"
    if status == "rejected":
        return "rejected"
    return "candidate"


def _review_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("reviewed_at") or ""),
        str(item.get("kind") or ""),
        str(item.get("source_id") or item.get("evidence_id") or ""),
    )


def _sorted_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (str(item.get("id") or ""), json.dumps(item, ensure_ascii=False, sort_keys=True)))


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_ref(value: str) -> str:
    return str(value).replace("\\", "/")


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
