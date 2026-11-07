from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .bounded_deep_loop import BoundedDeepLoopError, run_bounded_deep_loop
from .storage import read_json, write_json
from .research_output import research_output_schema_path


PACK_SCHEMA = "question-research-offline-evidence-brief.v1"
PACK_VERSION = "1.0.0"
PROJECTION_RECEIPT_SCHEMA = "question-research-offline-projection-receipt.v1"
FIXTURE_VERSION = "1.0.0"
DELIVERABLES = (
    "research-plan.v1.json",
    "evidence-bundle.v1.json",
    "claim-graph.v1.json",
    "gap-review.v1.json",
    "content-brief.v1.json",
    "review-packet.v1.json",
)
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def run_offline_evidence_brief(
    fixture_path: str | Path,
    output_root: str | Path,
    *,
    closure_run_id: str | None = None,
    resume: bool = False,
    stop_after: str | None = None,
    core_crash_after: str | None = None,
    projection_crash_after: str | None = None,
) -> dict[str, Any]:
    """Project the existing bounded loop into shared candidate-only artifacts."""
    if projection_crash_after not in {None, "deliverables", "receipt"}:
        raise BoundedDeepLoopError(
            "invalid_projection_crash_stage",
            "projection_crash_after must be deliverables or receipt",
        )

    fixture_file = Path(fixture_path).resolve()
    fixture = _load_fixture(fixture_file)
    _validate_projection_inputs(fixture)
    migration = _fixture_migration(fixture)

    core_result = run_bounded_deep_loop(
        fixture_file,
        output_root,
        closure_run_id=closure_run_id,
        resume=resume,
        stop_after=stop_after,
        crash_after=core_crash_after,
    )
    if core_result["execution_status"] != "complete":
        return {
            **core_result,
            "schema": PACK_SCHEMA,
            "projection_status": "waiting_for_core_resume",
            "deliverables": [],
        }

    run_dir = Path(core_result["run_dir"]).resolve()
    core_manifest_path = Path(core_result["manifest_path"]).resolve()
    if run_dir not in core_manifest_path.parents:
        raise BoundedDeepLoopError("core_manifest_path_escape", "core manifest is outside the run directory")
    core_manifest = _read_object(core_manifest_path, "core_manifest_corrupt")
    artifacts = _load_core_artifacts(run_dir, core_manifest)
    input_sha256 = str(core_manifest["input_sha256"])
    projection_root = run_dir / "deliverables"
    pack_path = run_dir / "offline-evidence-brief.v1.json"
    receipt_path = projection_root / "projection-receipt.v1.json"

    partial_projection = projection_root.exists() and any(projection_root.iterdir()) and not pack_path.is_file()
    if partial_projection and not resume:
        raise BoundedDeepLoopError(
            "projection_resume_required",
            "partial projection exists; rerun with --resume",
        )

    payloads = _build_deliverables(
        fixture,
        artifacts,
        closure_run_id=str(core_manifest["closure_run_id"]),
        input_sha256=input_sha256,
        fixture_name=fixture_file.name,
    )
    rows: list[dict[str, str]] = []
    for name in DELIVERABLES:
        path = projection_root / name
        _write_or_validate(path, payloads[name], drift_code="projection_artifact_drift")
        rows.append({"name": name, "path": f"deliverables/{name}", "sha256": _sha256(path.read_bytes())})

    if projection_crash_after == "deliverables":
        raise BoundedDeepLoopError(
            "synthetic_projection_crash_injected",
            "deliverables persisted before projection receipt",
        )

    receipt = {
        "schema": PROJECTION_RECEIPT_SCHEMA,
        "schema_version": PACK_VERSION,
        "closure_run_id": core_manifest["closure_run_id"],
        "input_sha256": input_sha256,
        "core_manifest_sha256": _sha256(core_manifest_path.read_bytes()),
        "core_receipt_chain_sha256": _sha256(_canonical_bytes(core_manifest["stage_receipts"])),
        "artifacts": rows,
        "status": "candidate_only",
        "network_called": False,
        "provider_called": False,
        "external_write_performed": False,
        "recorded_at": fixture["observed_at"],
    }
    _write_or_validate(receipt_path, receipt, drift_code="projection_receipt_drift")
    receipt_row = {
        "path": "deliverables/projection-receipt.v1.json",
        "sha256": _sha256(receipt_path.read_bytes()),
    }

    if projection_crash_after == "receipt":
        raise BoundedDeepLoopError(
            "synthetic_projection_crash_injected",
            "projection receipt persisted before pack manifest",
        )

    pack = {
        "schema": PACK_SCHEMA,
        "schema_version": PACK_VERSION,
        "closure_run_id": core_manifest["closure_run_id"],
        "input_sha256": input_sha256,
        "question": fixture["question"],
        "status": core_manifest["research_status"],
        "artifact_state": "candidate_only",
        "core": {
            "contract": core_manifest["schema"],
            "contract_version": core_manifest["schema_version"],
            "manifest_path": "bounded-deep-loop.v1.json",
            "manifest_sha256": _sha256(core_manifest_path.read_bytes()),
            "stage_receipts": core_manifest["stage_receipts"],
        },
        "input_contract_migration": migration,
        "deliverables": rows,
        "projection_receipt": receipt_row,
        "resume_from": None,
        "review_required": True,
        "finalization_authorized": False,
        "source_reuse": [
            {
                "owner": "question-research-poc",
                "contract": "research-output.v1",
                "module": "schemas/research-output.v1.schema.json",
                "effect": "canonical_candidate_projection",
            },
            {
                "owner": "ai-research-workflow",
                "contract": "evidence-bundle.v1",
                "module": "src/research_workflow/evidence_bundle_reference.py",
                "effect": "reference_validation_only_not_executed",
            },
            {
                "owner": "web-content-fetcher",
                "contract": "evidence_archive",
                "module": "web_content_fetcher/archive.py",
                "effect": "hash_bound_archive_metadata_only",
            },
            {
                "owner": "research-content-production",
                "contract": "content-brief.v1/review-packet.v1",
                "module": "docs/local-tools/contracts/linkage-contract-catalog.v1.json",
                "effect": "candidate_facade_projection_only",
            },
        ],
        "truth_dimensions": core_manifest["truth_dimensions"],
        "boundaries": core_manifest["boundaries"],
        "created_at": fixture["observed_at"],
    }
    _write_or_validate(pack_path, pack, drift_code="pack_manifest_drift")
    return {
        "ok": True,
        "schema": PACK_SCHEMA,
        "execution_status": "complete",
        "projection_status": "complete_candidate_only",
        "research_status": core_manifest["research_status"],
        "closure_run_id": core_manifest["closure_run_id"],
        "run_dir": str(run_dir),
        "manifest_path": str(pack_path),
        "manifest_sha256": _sha256(pack_path.read_bytes()),
        "core_manifest_path": str(core_manifest_path),
        "deliverables": rows,
        "projection_receipt": receipt_row,
        "resume_from": None,
        "finalization_authorized": False,
        "reused": bool(core_result.get("reused")) and pack_path.is_file(),
        "truth_dimensions": core_manifest["truth_dimensions"],
    }


def _build_deliverables(
    fixture: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    *,
    closure_run_id: str,
    input_sha256: str,
    fixture_name: str,
) -> dict[str, dict[str, Any]]:
    plan = _research_plan(fixture, artifacts, closure_run_id, input_sha256)
    bundle = _evidence_bundle(fixture, artifacts, closure_run_id, input_sha256, fixture_name)
    _validate_research_output(bundle)
    claim_graph = _claim_graph(artifacts, closure_run_id, input_sha256)
    gap_review = _gap_review(artifacts, closure_run_id, input_sha256)
    content_brief = _content_brief(artifacts, closure_run_id, input_sha256)
    reference_hashes = {
        "evidence_bundle": _sha256(_json_bytes(bundle)),
        "claim_graph": _sha256(_json_bytes(claim_graph)),
        "gap_review": _sha256(_json_bytes(gap_review)),
        "content_brief": _sha256(_json_bytes(content_brief)),
    }
    review_packet = _review_packet(artifacts, closure_run_id, input_sha256, reference_hashes)
    return {
        "research-plan.v1.json": plan,
        "evidence-bundle.v1.json": bundle,
        "claim-graph.v1.json": claim_graph,
        "gap-review.v1.json": gap_review,
        "content-brief.v1.json": content_brief,
        "review-packet.v1.json": review_packet,
    }


def _research_plan(
    fixture: dict[str, Any], artifacts: dict[str, dict[str, Any]], closure_run_id: str, input_sha256: str
) -> dict[str, Any]:
    intake = artifacts["intake"]
    return {
        "schema": "question-research-offline-plan.v1",
        "closure_run_id": closure_run_id,
        "input_sha256": input_sha256,
        "question": fixture["question"],
        "audience": fixture["audience"],
        "budgets": intake["budgets"],
        "selected_subquestions": intake["selected_subquestions"],
        "deferred_subquestions": intake["deferred_subquestions"],
        "selection_policy": intake["selection_policy"],
        "status": "candidate_only",
        "online_expansion_authorized": False,
    }


def _evidence_bundle(
    fixture: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    closure_run_id: str,
    input_sha256: str,
    fixture_name: str,
) -> dict[str, Any]:
    admission = artifacts["source_admission"]
    analysis = artifacts["evidence_analysis"]
    admitted_ids = {item["source_id"] for item in admission["admitted_sources"]}
    source_by_id = {item["source_id"]: item for item in fixture["sources"] if item["source_id"] in admitted_ids}
    sources = []
    for source_id in sorted(source_by_id):
        source = source_by_id[source_id]
        canonical_ref = str(source["canonical_ref"])
        url = canonical_ref if canonical_ref.startswith(("http://", "https://")) else None
        archive_path = str(source.get("archive_path") or canonical_ref)
        sources.append(
            {
                "source_id": source_id,
                "title": source["title"],
                "url": url,
                "archive_path": archive_path,
                "source_type": source["source_type"],
                "publisher": source.get("publisher") or "Synthetic Fixture Publisher",
                "fetched_at": fixture["observed_at"],
                "freshness": source["freshness"],
                "hash": {"algorithm": "sha256", "value": source["content_sha256"], "status": "verified"},
                "quality": source["quality"],
                "review_status": source["review_status"],
                "ref_status": "resolved",
                "provenance": {
                    "created_at": fixture["observed_at"],
                    "review_refs": [f"fixture-source-review:{source_id}"] if source["review_status"] == "reviewed" else [],
                    "note_fields": {
                        "canonical_ref": canonical_ref,
                        "artifact_sha256": source["content_sha256"],
                        "archive_contract": str(source.get("archive_contract") or "inline_fixture.v1"),
                    },
                },
            }
        )

    evidence_rows = []
    for item in analysis["evidence_records"]:
        source = source_by_id[item["source_id"]]
        verified_fact = bool(item["usable_as_source_fact"])
        evidence_rows.append(
            {
                "evidence_id": item["evidence_id"],
                "claim_id": item["claim_id"],
                "source_id": item["source_id"],
                "relation": item["relation"],
                "evidence_status": "verified" if verified_fact else "candidate",
                "review_status": item["review_status"],
                "confidence": "high" if verified_fact else "unknown",
                "excerpt": _truncate(str(item["text"]), 160),
                "observed_at": fixture["observed_at"],
                "source_path": str(source.get("archive_path") or source["canonical_ref"]),
                "artifact_sha256": source["content_sha256"],
                "ai_synthesis": item["evidence_type"] == "agent_inference",
            }
        )
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in evidence_rows:
        evidence_by_claim.setdefault(item["claim_id"], []).append(item)

    claims = []
    for claim in analysis["claims"]:
        linked = evidence_by_claim.get(claim["claim_id"], [])
        status = "missing" if claim["evidence_status"] == "unknown" else "contradicted" if claim["evidence_status"] == "contradicted" else "candidate"
        claims.append(
            {
                "claim_id": claim["claim_id"],
                "text": claim["text"],
                "claim_status": "open",
                "review_status": "candidate",
                "evidence_status": status,
                "evidence_ids": sorted(item["evidence_id"] for item in linked),
                "supporting_evidence_ids": sorted(item["evidence_id"] for item in linked if item["relation"] == "supports"),
                "contradicting_evidence_ids": sorted(item["evidence_id"] for item in linked if item["relation"] == "contradicts"),
                "context_evidence_ids": sorted(item["evidence_id"] for item in linked if item["relation"] == "context"),
                "source_ids": sorted({item["source_id"] for item in linked}),
            }
        )
    links = [
        {
            "evidence_id": item["evidence_id"],
            "claim_id": item["claim_id"],
            "source_id": item["source_id"],
            "relation": item["relation"],
            "evidence_status": item["evidence_status"],
        }
        for item in evidence_rows
    ]
    contradictions = [
        {
            "claim_id": item["claim_id"],
            "evidence_id": item["evidence_id"],
            "source_id": item["source_id"],
            "evidence_status": item["evidence_status"],
            "resolution_status": "unresolved",
        }
        for item in evidence_rows
        if item["relation"] == "contradicts"
    ]
    unknowns = [
        {
            "code": f"evidence_gap:{item['claim_id']}",
            "severity": "blocker",
            "message": item["reason"],
            "claim_id": item["claim_id"],
            "source_id": None,
            "evidence_id": None,
        }
        for item in analysis["unknowns"]
    ]
    unknowns.extend(
        {
            "code": blocker,
            "severity": "blocker",
            "message": "Source admission blocked by integrity validation.",
            "claim_id": None,
            "source_id": blocker.split(":", 1)[1] if ":" in blocker else None,
            "evidence_id": None,
        }
        for blocker in admission["blockers"]
    )
    blockers = {"human_review_required"}
    blockers.update(item["code"] for item in unknowns)
    blockers.update(f"unresolved_contradiction:{item['claim_id']}" for item in contradictions)
    blockers.update(f"candidate_evidence:{item['evidence_id']}" for item in evidence_rows if item["evidence_status"] == "candidate")
    candidate_count = sum(item["evidence_status"] == "candidate" for item in evidence_rows)
    verified_count = sum(item["evidence_status"] == "verified" for item in evidence_rows)
    return {
        "schema": "research-output.v1",
        "schema_version": "1.0.0",
        "research_id": closure_run_id,
        "question": fixture["question"],
        "scope": {
            "statement": "Offline bounded evidence-to-brief acceptance run.",
            "constraints": ["candidate-only", "no-external-api", "no-model-memory", "synthetic-or-deidentified-fixture"],
        },
        "audience": fixture["audience"],
        "requested_outputs": ["article", "review-packet.v1"],
        "sources": sources,
        "claims": claims,
        "evidence": evidence_rows,
        "evidence_links": links,
        "contradictions": contradictions,
        "unknowns": unknowns,
        "review_status": {"overall": "candidate", "human_review_required": True, "events": []},
        "evidence_status": {
            "overall": "contradicted" if contradictions else "candidate",
            "counts": {
                "candidate": candidate_count,
                "verified": verified_count,
                "rejected": 0,
                "contradictions": len(contradictions),
            },
        },
        "completeness": {
            "ready_for_answer": False,
            "blocking_gates": sorted(blockers),
            "warnings": ["Synthetic or deidentified fixture evidence is not real-world usage proof."],
            "coverage": {
                "source_count": len(sources),
                "claim_count": len(claims),
                "claims_with_evidence": sum(bool(item["evidence_ids"]) for item in claims),
                "candidate_evidence": candidate_count,
                "unresolved_contradictions": len(contradictions),
                "unknown_count": len(unknowns),
            },
        },
        "guarded_final_answer": {
            "status": "blocked",
            "ready": False,
            "answer": None,
            "claim_ids": [],
            "evidence_ids": [],
            "source_ids": [],
            "blocking_gates": sorted(blockers),
            "warnings": ["Use the guarded synthesis only as a candidate for human review."],
            "guardrail": "Candidate evidence and synthetic review state cannot be promoted to a verified final answer.",
        },
        "media_refs": [],
        "visual_leads": [],
        "quotable_facts": [],
        "provenance": {
            "input_files": [{"path": fixture_name, "sha256": input_sha256, "status": "present"}],
            "source_systems": ["question-research-poc", "web-content-fetcher-archive-contract"],
            "offline_only": True,
            "external_api_called": False,
            "model_memory_used_as_evidence": False,
        },
        "generator": {"name": "question-research-poc", "component": "research_output", "version": "research-output.v1"},
        "created_at": fixture["observed_at"],
    }


def _claim_graph(artifacts: dict[str, dict[str, Any]], closure_run_id: str, input_sha256: str) -> dict[str, Any]:
    analysis = artifacts["evidence_analysis"]
    nodes = [
        {"node_id": item["claim_id"], "kind": "claim", "text": item["text"], "status": item["evidence_status"]}
        for item in analysis["claims"]
    ]
    nodes.extend(
        {"node_id": item["evidence_id"], "kind": "evidence", "text": item["text"], "status": "candidate_only"}
        for item in analysis["evidence_records"]
    )
    edges = [
        {
            "from_id": item["evidence_id"],
            "to_id": item["claim_id"],
            "relation": item["relation"],
            "source_id": item["source_id"],
            "status": "candidate_only",
        }
        for item in analysis["evidence_records"]
    ]
    return {
        "schema": "question-research-claim-graph-candidate.v1",
        "closure_run_id": closure_run_id,
        "input_sha256": input_sha256,
        "status": "candidate_only",
        "nodes": nodes,
        "edges": edges,
        "human_review_required": True,
    }


def _gap_review(artifacts: dict[str, dict[str, Any]], closure_run_id: str, input_sha256: str) -> dict[str, Any]:
    analysis = artifacts["evidence_analysis"]
    return {
        "schema": "question-research-gap-review.v1",
        "closure_run_id": closure_run_id,
        "input_sha256": input_sha256,
        "status": "candidate_only",
        "unknowns": analysis["unknowns"],
        "contradictions": analysis["contradictions"],
        "deferred_subquestions": artifacts["intake"]["deferred_subquestions"],
        "source_blockers": artifacts["source_admission"]["blockers"],
        "search_stop_reason": analysis["stop_reason"],
        "online_followup": {"status": "blocked_by_design", "execution_authorized": False},
        "resume_from": None,
    }


def _content_brief(artifacts: dict[str, dict[str, Any]], closure_run_id: str, input_sha256: str) -> dict[str, Any]:
    brief = artifacts["article_brief"]
    return {
        "schema_version": "content-brief.v1",
        "facade_contract": "content-brief.v1",
        "native_contract": brief["schema"],
        "variant": "article",
        "closure_run_id": closure_run_id,
        "input_sha256": input_sha256,
        "status": "candidate_only",
        "mode": "draft_only",
        "title": brief["title"],
        "audience": brief["audience"],
        "angle": brief["angle"],
        "sections": brief["sections"],
        "contradictions": brief["contradictions"],
        "unknowns": brief["unknowns"],
        "search_stop_reason": brief["search_stop_reason"],
        "review_gate": brief["review_packet"],
        "authority": brief["authority"],
    }


def _review_packet(
    artifacts: dict[str, dict[str, Any]],
    closure_run_id: str,
    input_sha256: str,
    reference_hashes: dict[str, str],
) -> dict[str, Any]:
    synthesis = artifacts["guarded_synthesis"]
    analysis = artifacts["evidence_analysis"]
    return {
        "schema_version": "review-packet.v1",
        "facade_contract": "review-packet.v1",
        "native_contract": "question-research-offline-review-packet.v1",
        "producer": "question-research-poc",
        "closure_run_id": closure_run_id,
        "input_sha256": input_sha256,
        "status": "pending_human_review",
        "evidence_status": "candidate",
        "suggested_points": [
            "Review every admitted source hash and freshness field.",
            "Resolve contradictions and unknowns before any final-answer request.",
            "Keep the content brief draft-only and preserve claim/evidence/source references.",
        ],
        "blocking_gates": synthesis["blocking_gates"],
        "contradictions": analysis["contradictions"],
        "unknowns": analysis["unknowns"],
        "evidence_refs": [f"sha256:{digest}#{name}" for name, digest in sorted(reference_hashes.items())],
        "decision_question": "Should this candidate-only offline pack proceed to explicit human review?",
        "authority": {
            "execution_authorized": False,
            "publish_authorized": False,
            "upload_authorized": False,
            "evidence_promotion_authorized": False,
        },
    }


def _load_core_artifacts(run_dir: Path, core_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = core_manifest.get("stage_receipts") or []
    if len(rows) != 5:
        raise BoundedDeepLoopError("core_receipt_chain_incomplete", "core stage receipt chain is incomplete")
    artifacts: dict[str, dict[str, Any]] = {}
    for row in rows:
        relative = str(row.get("artifact_path") or "")
        path = (run_dir / relative).resolve()
        if run_dir not in path.parents or not path.is_file():
            raise BoundedDeepLoopError("core_artifact_path_escape", f"invalid core artifact path: {relative}")
        if _sha256(path.read_bytes()) != row.get("artifact_sha256"):
            raise BoundedDeepLoopError("core_artifact_hash_drift", f"core artifact drift: {relative}")
        artifacts[str(row["stage_id"])] = _read_object(path, "core_artifact_corrupt")
    return artifacts


def _load_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BoundedDeepLoopError("fixture_missing", f"fixture does not exist: {path}")
    return _read_object(path, "fixture_corrupt")


def _fixture_migration(fixture: dict[str, Any]) -> dict[str, Any]:
    version = fixture.get("contract_version")
    if version is None:
        return {
            "applied": True,
            "from": "unversioned-legacy-fixture",
            "to": FIXTURE_VERSION,
            "semantic_change": False,
        }
    if version != FIXTURE_VERSION:
        raise BoundedDeepLoopError("fixture_contract_version_unsupported", f"unsupported fixture contract_version: {version}")
    return {"applied": False, "from": FIXTURE_VERSION, "to": FIXTURE_VERSION, "semantic_change": False}


def _validate_projection_inputs(fixture: dict[str, Any]) -> None:
    _fixture_migration(fixture)
    for source in fixture.get("sources") or []:
        archive_path = str(source.get("archive_path") or "")
        if archive_path and not _safe_relative_reference(archive_path):
            raise BoundedDeepLoopError("source_archive_path_escape", f"unsafe archive_path for {source.get('source_id')}")
        archive_hash = source.get("archive_content_sha256")
        if archive_hash is not None and archive_hash != source.get("content_sha256"):
            raise BoundedDeepLoopError("source_archive_hash_drift", f"archive hash drift for {source.get('source_id')}")
    for item in fixture.get("evidence") or []:
        if not str(item.get("text") or "").strip():
            raise BoundedDeepLoopError("evidence_citation_missing", f"evidence text is missing for {item.get('evidence_id')}")


def _safe_relative_reference(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_PREFIX.match(normalized):
        return False
    return ".." not in PurePosixPath(normalized).parts


def _validate_research_output(payload: dict[str, Any]) -> None:
    schema_path = research_output_schema_path()
    try:
        import jsonschema
    except ImportError as exc:
        raise BoundedDeepLoopError("validator_unavailable", "project-local jsonschema is required") from exc
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        detail = "; ".join(f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors[:8])
        raise BoundedDeepLoopError("evidence_bundle_contract_invalid", detail)


def _write_or_validate(path: Path, payload: dict[str, Any], *, drift_code: str) -> None:
    expected = _json_bytes(payload)
    if path.is_file():
        if path.read_bytes() != expected:
            raise BoundedDeepLoopError(drift_code, f"existing artifact drift: {path.name}")
        return
    write_json(path, payload)


def _read_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = read_json(path)
    except Exception as exc:
        raise BoundedDeepLoopError(code, f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BoundedDeepLoopError(code, f"JSON root must be an object: {path}")
    return value


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
