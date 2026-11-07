from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .storage import read_json, write_json


CONTRACT = "question-research-bounded-deep-loop.v1"
FIXTURE_CONTRACT = "question-research-bounded-deep-loop-fixture.v1"
RECEIPT_CONTRACT = "question-research-bounded-deep-loop-stage-receipt.v1"
ARTICLE_BRIEF_CONTRACT = "question-research-article-brief-candidate.v1"
CONTRACT_VERSION = "1.0.0"
STAGES = (
    "intake",
    "source_admission",
    "evidence_analysis",
    "guarded_synthesis",
    "article_brief",
)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")


class BoundedDeepLoopError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def bounded_deep_loop_schema_path() -> Path:
    source_tree = Path(__file__).resolve().parents[2] / "schemas" / "question-research-bounded-deep-loop.v1.schema.json"
    if source_tree.is_file():
        return source_tree
    return Path(__file__).resolve().parent / "schemas" / "question-research-bounded-deep-loop.v1.schema.json"


def run_bounded_deep_loop(
    fixture_path: str | Path,
    output_root: str | Path,
    *,
    closure_run_id: str | None = None,
    resume: bool = False,
    stop_after: str | None = None,
    crash_after: str | None = None,
    request_finalize: bool = False,
) -> dict[str, Any]:
    """Run one deterministic, offline, evidence-bounded research action."""
    if stop_after is not None and stop_after not in STAGES:
        raise BoundedDeepLoopError("invalid_stop_stage", f"stop_after must be one of: {', '.join(STAGES)}")
    if crash_after is not None and crash_after not in STAGES:
        raise BoundedDeepLoopError("invalid_crash_stage", f"crash_after must be one of: {', '.join(STAGES)}")

    fixture_file = Path(fixture_path).resolve()
    fixture = _load_fixture(fixture_file)
    input_sha256 = _sha256(_canonical_bytes(fixture))
    run_id = closure_run_id or f"deep-loop-{input_sha256[:20]}"
    if not _RUN_ID.fullmatch(run_id):
        raise BoundedDeepLoopError("invalid_closure_run_id", "closure_run_id contains unsupported characters")

    run_dir = Path(output_root).resolve() / run_id
    checkpoint_path = run_dir / "checkpoint.json"
    manifest_path = run_dir / "bounded-deep-loop.v1.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(exist_ok=True)
    (run_dir / "receipts").mkdir(exist_ok=True)

    state = _load_or_create_checkpoint(checkpoint_path, run_id, input_sha256, fixture)
    receipts, artifacts = _validate_and_recover_chain(run_dir, state, run_id, input_sha256)
    state = _checkpoint(fixture, run_id, input_sha256, receipts, completed=len(receipts) == len(STAGES))
    write_json(checkpoint_path, state)

    if request_finalize:
        if len(receipts) != len(STAGES) or not manifest_path.is_file():
            raise BoundedDeepLoopError(
                "early_finalize_rejected",
                f"research stages are incomplete; resume_from={STAGES[len(receipts)]}",
            )
        manifest = _validate_manifest(manifest_path, run_id, input_sha256, receipts)
        return _result(run_dir, manifest, reused=True, finalized=False)

    if receipts and not resume and len(receipts) != len(STAGES):
        raise BoundedDeepLoopError(
            "resume_required",
            f"partial run exists; rerun with --resume from {STAGES[len(receipts)]}",
        )

    if len(receipts) == len(STAGES):
        if manifest_path.is_file():
            manifest = _validate_manifest(manifest_path, run_id, input_sha256, receipts)
            return _result(run_dir, manifest, reused=True)
        if not resume:
            raise BoundedDeepLoopError(
                "resume_required",
                "all stage receipts exist but the final manifest is missing; rerun with --resume",
            )
        manifest = _build_manifest(fixture, run_id, input_sha256, receipts, artifacts)
        _validate_contract(manifest)
        write_json(manifest_path, manifest)
        write_json(checkpoint_path, _checkpoint(fixture, run_id, input_sha256, receipts, completed=True))
        return _result(run_dir, manifest, reused=True)

    builders: dict[str, Callable[[dict[str, Any], dict[str, dict[str, Any]]], dict[str, Any]]] = {
        "intake": _build_intake,
        "source_admission": _build_source_admission,
        "evidence_analysis": _build_evidence_analysis,
        "guarded_synthesis": _build_guarded_synthesis,
        "article_brief": _build_article_brief,
    }
    previous_receipt_sha256 = receipts[-1]["receipt_sha256"] if receipts else None
    for index in range(len(receipts), len(STAGES)):
        stage_id = STAGES[index]
        artifact = builders[stage_id](fixture, artifacts)
        artifact_rel = f"artifacts/{index + 1:02d}-{stage_id}.json"
        artifact_path = run_dir / artifact_rel
        write_json(artifact_path, artifact)
        artifact_sha256 = _sha256(artifact_path.read_bytes())
        receipt = {
            "schema": RECEIPT_CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "closure_run_id": run_id,
            "stage_id": stage_id,
            "stage_index": index + 1,
            "input_sha256": input_sha256,
            "previous_receipt_sha256": previous_receipt_sha256,
            "artifact": {"path": artifact_rel, "sha256": artifact_sha256},
            "execution_status": "complete",
            "research_state": _stage_research_state(stage_id, artifact),
            "network_called": False,
            "provider_called": False,
            "external_write_performed": False,
            "recorded_at": fixture["observed_at"],
        }
        receipt_rel = f"receipts/{index + 1:02d}-{stage_id}.json"
        receipt_path = run_dir / receipt_rel
        write_json(receipt_path, receipt)
        receipt_sha256 = _sha256(_canonical_bytes(receipt))
        if crash_after == stage_id:
            raise BoundedDeepLoopError(
                "synthetic_crash_injected",
                f"receipt persisted before checkpoint at stage {stage_id}",
            )
        receipt_row = {
            "stage_id": stage_id,
            "stage_index": index + 1,
            "path": receipt_rel,
            "receipt_sha256": receipt_sha256,
            "artifact_path": artifact_rel,
            "artifact_sha256": artifact_sha256,
        }
        receipts.append(receipt_row)
        artifacts[stage_id] = artifact
        previous_receipt_sha256 = receipt_sha256
        state = _checkpoint(fixture, run_id, input_sha256, receipts, completed=False)
        write_json(checkpoint_path, state)
        if stop_after == stage_id:
            return {
                "ok": True,
                "execution_status": "paused",
                "research_status": _stage_research_state(stage_id, artifact),
                "closure_run_id": run_id,
                "run_dir": str(run_dir),
                "completed_stages": [item["stage_id"] for item in receipts],
                "resume_from": STAGES[len(receipts)] if len(receipts) < len(STAGES) else None,
                "finalization_authorized": False,
            }

    manifest = _build_manifest(fixture, run_id, input_sha256, receipts, artifacts)
    _validate_contract(manifest)
    write_json(manifest_path, manifest)
    write_json(checkpoint_path, _checkpoint(fixture, run_id, input_sha256, receipts, completed=True))
    return _result(run_dir, manifest, reused=False)


def _load_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BoundedDeepLoopError("fixture_missing", f"fixture does not exist: {path}")
    try:
        payload = read_json(path)
    except Exception as exc:
        raise BoundedDeepLoopError("fixture_corrupt", f"fixture is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise BoundedDeepLoopError("fixture_invalid", "fixture root must be an object")
    if payload.get("schema") != FIXTURE_CONTRACT:
        raise BoundedDeepLoopError("fixture_contract_mismatch", f"expected {FIXTURE_CONTRACT}")
    required = {"fixture_id", "question", "observed_at", "audience", "budgets", "subquestions", "sources", "claims", "evidence"}
    missing = sorted(required - set(payload))
    if missing:
        raise BoundedDeepLoopError("fixture_invalid", f"missing fixture fields: {', '.join(missing)}")
    _validate_fixture_semantics(payload)
    return payload


def _validate_fixture_semantics(fixture: dict[str, Any]) -> None:
    budgets = fixture.get("budgets") or {}
    for field in ("max_subquestions", "max_depth", "max_sources", "max_tokens", "max_expansions_per_round"):
        value = budgets.get(field)
        if not isinstance(value, int) or value < 1:
            raise BoundedDeepLoopError("fixture_budget_invalid", f"{field} must be a positive integer")
    minimum_gap = budgets.get("minimum_gap_score", 0.0)
    if not isinstance(minimum_gap, (int, float)) or not 0 <= minimum_gap <= 1:
        raise BoundedDeepLoopError("fixture_budget_invalid", "minimum_gap_score must be between 0 and 1")
    for key, id_key in (("subquestions", "subquestion_id"), ("sources", "source_id"), ("claims", "claim_id"), ("evidence", "evidence_id")):
        rows = fixture.get(key)
        if not isinstance(rows, list) or not rows:
            raise BoundedDeepLoopError("fixture_invalid", f"{key} must be a non-empty array")
        ids = [str(row.get(id_key) or "") for row in rows if isinstance(row, dict)]
        if len(ids) != len(rows) or not all(ids) or len(set(ids)) != len(ids):
            raise BoundedDeepLoopError("fixture_duplicate_id", f"{key} contains missing or duplicate {id_key}")
    subquestion_ids = {row["subquestion_id"] for row in fixture["subquestions"]}
    source_ids = {row["source_id"] for row in fixture["sources"]}
    claim_ids = {row["claim_id"] for row in fixture["claims"]}
    for claim in fixture["claims"]:
        if claim.get("subquestion_id") not in subquestion_ids:
            raise BoundedDeepLoopError("fixture_reference_missing", f"claim {claim['claim_id']} has no subquestion")
    for item in fixture["evidence"]:
        if item.get("claim_id") not in claim_ids or item.get("source_id") not in source_ids:
            raise BoundedDeepLoopError("fixture_reference_missing", f"evidence {item['evidence_id']} has a missing reference")
        if item.get("evidence_type") not in {"source_fact", "source_claim", "agent_inference"}:
            raise BoundedDeepLoopError("fixture_evidence_type_invalid", f"invalid evidence_type for {item['evidence_id']}")
        if item.get("relation") not in {"supports", "contradicts", "context"}:
            raise BoundedDeepLoopError("fixture_relation_invalid", f"invalid relation for {item['evidence_id']}")


def _load_or_create_checkpoint(
    path: Path,
    run_id: str,
    input_sha256: str,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        state = _checkpoint(fixture, run_id, input_sha256, [], completed=False)
        write_json(path, state)
        return state
    try:
        state = read_json(path)
    except Exception as exc:
        raise BoundedDeepLoopError("checkpoint_corrupt", "checkpoint is not valid JSON") from exc
    if not isinstance(state, dict):
        raise BoundedDeepLoopError("checkpoint_corrupt", "checkpoint root must be an object")
    if state.get("closure_run_id") != run_id or state.get("input_sha256") != input_sha256:
        raise BoundedDeepLoopError("checkpoint_input_drift", "checkpoint does not match the current fixture/run")
    return state


def _validate_and_recover_chain(
    run_dir: Path,
    checkpoint: dict[str, Any],
    run_id: str,
    input_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}
    previous: str | None = None
    gap_seen = False
    for index, stage_id in enumerate(STAGES, start=1):
        receipt_rel = f"receipts/{index:02d}-{stage_id}.json"
        receipt_path = run_dir / receipt_rel
        if not receipt_path.is_file():
            gap_seen = True
            continue
        if gap_seen:
            raise BoundedDeepLoopError("receipt_order_invalid", f"receipt exists after a missing stage: {stage_id}")
        try:
            receipt = read_json(receipt_path)
        except Exception as exc:
            raise BoundedDeepLoopError("receipt_corrupt", f"invalid receipt JSON: {receipt_rel}") from exc
        if not isinstance(receipt, dict):
            raise BoundedDeepLoopError("receipt_corrupt", f"receipt root must be an object: {receipt_rel}")
        expected = {
            "schema": RECEIPT_CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "closure_run_id": run_id,
            "stage_id": stage_id,
            "stage_index": index,
            "input_sha256": input_sha256,
            "previous_receipt_sha256": previous,
        }
        drift = [key for key, value in expected.items() if receipt.get(key) != value]
        if drift:
            raise BoundedDeepLoopError("receipt_binding_drift", f"{receipt_rel} drift: {', '.join(drift)}")
        artifact_meta = receipt.get("artifact") or {}
        artifact_rel = str(artifact_meta.get("path") or "")
        expected_artifact_rel = f"artifacts/{index:02d}-{stage_id}.json"
        if artifact_rel != expected_artifact_rel:
            raise BoundedDeepLoopError("receipt_artifact_path_drift", f"unexpected artifact path for {stage_id}")
        artifact_path = run_dir / artifact_rel
        if not artifact_path.is_file():
            raise BoundedDeepLoopError("receipt_artifact_missing", f"artifact missing for {stage_id}")
        artifact_sha256 = _sha256(artifact_path.read_bytes())
        if artifact_sha256 != artifact_meta.get("sha256"):
            raise BoundedDeepLoopError("receipt_artifact_hash_drift", f"artifact hash drift for {stage_id}")
        try:
            artifact = read_json(artifact_path)
        except Exception as exc:
            raise BoundedDeepLoopError("artifact_corrupt", f"artifact is not valid JSON: {artifact_rel}") from exc
        receipt_sha256 = _sha256(_canonical_bytes(receipt))
        rows.append(
            {
                "stage_id": stage_id,
                "stage_index": index,
                "path": receipt_rel,
                "receipt_sha256": receipt_sha256,
                "artifact_path": artifact_rel,
                "artifact_sha256": artifact_sha256,
            }
        )
        artifacts[stage_id] = artifact
        previous = receipt_sha256

    recorded = checkpoint.get("receipts") or []
    if not isinstance(recorded, list):
        raise BoundedDeepLoopError("checkpoint_corrupt", "checkpoint receipts must be an array")
    for index, row in enumerate(recorded):
        if index >= len(rows) or row != rows[index]:
            raise BoundedDeepLoopError("checkpoint_receipt_drift", "checkpoint receipt chain does not match persisted receipts")
    return rows, artifacts


def _build_intake(fixture: dict[str, Any], _: dict[str, dict[str, Any]]) -> dict[str, Any]:
    budgets = fixture["budgets"]
    priority = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for item in fixture["subquestions"]:
        reason = ""
        if int(item.get("depth", 1)) > budgets["max_depth"]:
            reason = "depth_limit"
        elif float(item.get("gap_score", 0)) < float(budgets.get("minimum_gap_score", 0)):
            reason = "low_marginal_gap"
        if reason:
            rejected.append({"subquestion_id": item["subquestion_id"], "reason": reason})
        else:
            eligible.append(item)
    eligible.sort(key=lambda item: (-float(item.get("gap_score", 0)), priority.get(str(item.get("priority", "P3")), 9), item["subquestion_id"]))
    limit = min(budgets["max_subquestions"], budgets["max_expansions_per_round"])
    selected = eligible[:limit]
    for item in eligible[limit:]:
        rejected.append({"subquestion_id": item["subquestion_id"], "reason": "subquestion_budget"})
    return {
        "schema": "question-research-bounded-intake.v1",
        "question": fixture["question"],
        "audience": fixture["audience"],
        "budgets": budgets,
        "round": 1,
        "selected_subquestions": selected,
        "deferred_subquestions": sorted(rejected, key=lambda item: item["subquestion_id"]),
        "selection_policy": "highest_evidence_gap_then_priority_with_depth_and_count_caps",
        "open_ended_expansion": False,
    }


def _build_source_admission(fixture: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    intake = artifacts["intake"]
    selected_ids = {item["subquestion_id"] for item in intake["selected_subquestions"]}
    claim_ids = {item["claim_id"] for item in fixture["claims"] if item["subquestion_id"] in selected_ids}
    relevant_source_ids = {item["source_id"] for item in fixture["evidence"] if item["claim_id"] in claim_ids}
    budgets = fixture["budgets"]
    used_tokens = sum(int(item.get("token_cost", 0)) for item in intake["selected_subquestions"])
    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    duplicate_sources: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    blockers: list[str] = []
    for source in fixture["sources"]:
        source_id = source["source_id"]
        if source_id not in relevant_source_ids:
            excluded.append({"source_id": source_id, "reason": "outside_selected_subquestions"})
            continue
        actual_hash = _sha256(str(source.get("content") or "").encode("utf-8"))
        if actual_hash != str(source.get("content_sha256") or ""):
            excluded.append({"source_id": source_id, "reason": "source_hash_mismatch"})
            blockers.append(f"source_hash_mismatch:{source_id}")
            continue
        dedupe_key = str(source.get("canonical_ref") or "").strip().casefold() or actual_hash
        if dedupe_key in seen:
            duplicate_sources.append({"source_id": source_id, "duplicate_of": seen[dedupe_key]})
            continue
        if len(admitted) >= budgets["max_sources"]:
            excluded.append({"source_id": source_id, "reason": "source_budget"})
            continue
        token_cost = int(source.get("token_cost", 0))
        if used_tokens + token_cost > budgets["max_tokens"]:
            excluded.append({"source_id": source_id, "reason": "token_budget"})
            continue
        seen[dedupe_key] = source_id
        used_tokens += token_cost
        admitted.append(
            {
                "source_id": source_id,
                "title": source["title"],
                "canonical_ref": source["canonical_ref"],
                "source_type": source["source_type"],
                "quality": source["quality"],
                "review_status": source["review_status"],
                "freshness": source["freshness"],
                "content_sha256": actual_hash,
                "token_cost": token_cost,
            }
        )
    return {
        "schema": "question-research-source-admission.v1",
        "selected_claim_ids": sorted(claim_ids),
        "admitted_sources": admitted,
        "duplicate_sources": duplicate_sources,
        "excluded_sources": excluded,
        "blockers": sorted(set(blockers)),
        "budget_usage": {
            "sources": len(admitted),
            "tokens": used_tokens,
            "source_limit": budgets["max_sources"],
            "token_limit": budgets["max_tokens"],
        },
        "new_evidence_source_count": len(admitted),
    }


def _build_evidence_analysis(fixture: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    admission = artifacts["source_admission"]
    admitted = {item["source_id"]: item for item in admission["admitted_sources"]}
    selected_claim_ids = set(admission["selected_claim_ids"])
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    records: list[dict[str, Any]] = []
    for item in fixture["evidence"]:
        if item["claim_id"] not in selected_claim_ids or item["source_id"] not in admitted:
            continue
        source = admitted[item["source_id"]]
        usable = (
            item.get("status") == "verified"
            and item.get("review_status") == "reviewed"
            and source["review_status"] == "reviewed"
            and source["quality"] == "good"
            and source["freshness"] in {"current", "not_applicable"}
            and item.get("evidence_type") == "source_fact"
        )
        row = {
            "evidence_id": item["evidence_id"],
            "claim_id": item["claim_id"],
            "source_id": item["source_id"],
            "evidence_type": item["evidence_type"],
            "relation": item["relation"],
            "status": item["status"],
            "review_status": item["review_status"],
            "text": item["text"],
            "usable_as_source_fact": usable,
        }
        records.append(row)
        evidence_by_claim.setdefault(item["claim_id"], []).append(row)
    claims: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    unknowns: list[dict[str, str]] = []
    for claim in fixture["claims"]:
        claim_id = claim["claim_id"]
        if claim_id not in selected_claim_ids:
            continue
        linked = evidence_by_claim.get(claim_id, [])
        supports = [item for item in linked if item["relation"] == "supports" and item["usable_as_source_fact"]]
        contradicts = [item for item in linked if item["relation"] == "contradicts" and item["usable_as_source_fact"]]
        if contradicts:
            status = "contradicted"
            contradictions.append(
                {
                    "claim_id": claim_id,
                    "supporting_evidence_ids": [item["evidence_id"] for item in supports],
                    "contradicting_evidence_ids": [item["evidence_id"] for item in contradicts],
                    "resolution_status": "human_review_required",
                }
            )
        elif supports:
            status = "supported"
        else:
            status = "unknown"
            reason = "no_admitted_evidence" if not linked else "no_reviewed_source_fact_support"
            unknowns.append({"claim_id": claim_id, "reason": reason})
        claims.append(
            {
                "claim_id": claim_id,
                "subquestion_id": claim["subquestion_id"],
                "text": claim["text"],
                "claim_origin": claim["claim_origin"],
                "evidence_status": status,
                "evidence_ids": [item["evidence_id"] for item in linked],
                "source_ids": sorted({item["source_id"] for item in linked}),
            }
        )
    stop_reason = "marginal_returns_reached"
    if admission["blockers"]:
        stop_reason = "source_integrity_blocked"
    elif not admission["admitted_sources"]:
        stop_reason = "no_new_evidence"
    elif any(item["reason"] in {"source_budget", "token_budget"} for item in admission["excluded_sources"]):
        stop_reason = "budget_exhausted"
    elif not any(item["evidence_status"] in {"supported", "contradicted"} for item in claims):
        stop_reason = "insufficient_evidence"
    return {
        "schema": "question-research-evidence-analysis.v1",
        "claims": claims,
        "evidence_records": records,
        "contradictions": contradictions,
        "unknowns": unknowns,
        "classification_counts": {
            "source_fact": sum(item["evidence_type"] == "source_fact" for item in records),
            "source_claim": sum(item["evidence_type"] == "source_claim" for item in records),
            "agent_inference": sum(item["evidence_type"] == "agent_inference" for item in records),
            "unknown": sum(item["evidence_status"] == "unknown" for item in claims),
            "contradicted": sum(item["evidence_status"] == "contradicted" for item in claims),
        },
        "stop_reason": stop_reason,
        "search_continuation_authorized": False,
    }


def _build_guarded_synthesis(fixture: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    analysis = artifacts["evidence_analysis"]
    supported = [item for item in analysis["claims"] if item["evidence_status"] == "supported"]
    blockers = [f"unknown:{item['claim_id']}" for item in analysis["unknowns"]]
    blockers.extend(f"contradiction:{item['claim_id']}" for item in analysis["contradictions"])
    blockers.extend(artifacts["source_admission"]["blockers"])
    status = "candidate_for_human_review" if supported else "blocked_insufficient_evidence"
    statements = [
        {
            "claim_id": item["claim_id"],
            "text": item["text"],
            "qualification": "supported_by_reviewed_synthetic_source_fact",
            "evidence_ids": item["evidence_ids"],
            "source_ids": item["source_ids"],
        }
        for item in supported
    ]
    return {
        "schema": "question-research-guarded-synthesis.v1",
        "question": fixture["question"],
        "status": status,
        "statements": statements,
        "blocking_gates": sorted(set(blockers)),
        "warnings": ["Synthetic fixture evidence is not real-world evidence and cannot establish real usage or current truth."],
        "stop_reason": analysis["stop_reason"],
        "human_review_required": True,
        "finalization_authorized": False,
        "model_memory_used_as_evidence": False,
    }


def _build_article_brief(fixture: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    synthesis = artifacts["guarded_synthesis"]
    analysis = artifacts["evidence_analysis"]
    sections = [
        {
            "section_id": f"section-{index:02d}",
            "heading": statement["text"],
            "claim_id": statement["claim_id"],
            "evidence_ids": statement["evidence_ids"],
            "source_ids": statement["source_ids"],
            "draft_instruction": "Present as evidence-bounded synthetic finding; preserve qualification.",
        }
        for index, statement in enumerate(synthesis["statements"], start=1)
    ]
    return {
        "schema": ARTICLE_BRIEF_CONTRACT,
        "schema_version": CONTRACT_VERSION,
        "mode": "draft_only",
        "title": fixture["question"],
        "audience": fixture["audience"],
        "angle": "Explain what the admitted evidence supports, what it contradicts, and why the loop stopped.",
        "sections": sections,
        "contradictions": analysis["contradictions"],
        "unknowns": analysis["unknowns"],
        "search_stop_reason": analysis["stop_reason"],
        "review_packet": {
            "status": "pending_human_review",
            "blocking_gates": synthesis["blocking_gates"],
            "human_confirmation_required": True,
        },
        "authority": {
            "execution_authorized": False,
            "publish_authorized": False,
            "external_write_authorized": False,
        },
        "source_material": "synthetic_fixture_only",
    }


def _build_manifest(
    fixture: dict[str, Any],
    run_id: str,
    input_sha256: str,
    receipts: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    synthesis = artifacts["guarded_synthesis"]
    brief = artifacts["article_brief"]
    return {
        "schema": CONTRACT,
        "schema_version": CONTRACT_VERSION,
        "closure_run_id": run_id,
        "fixture_id": fixture["fixture_id"],
        "input_sha256": input_sha256,
        "question": fixture["question"],
        "execution_status": "complete",
        "research_status": synthesis["status"],
        "search_stop_reason": synthesis["stop_reason"],
        "stage_receipts": receipts,
        "guarded_synthesis": synthesis,
        "article_brief": brief,
        "resume_from": None,
        "finalization_authorized": False,
        "truth_dimensions": {
            "contract_ready": True,
            "runtime_ready": True,
            "fresh_e2e_pass": True,
            "real_usage_proof": False,
            "current_online": False,
        },
        "boundaries": {
            "synthetic_or_public_only": True,
            "network_called": False,
            "provider_called": False,
            "service_started": False,
            "external_write_performed": False,
            "publication_performed": False,
            "silent_fallback_used": False,
            "model_memory_used_as_evidence": False,
        },
        "created_at": fixture["observed_at"],
    }


def _validate_manifest(
    path: Path,
    run_id: str,
    input_sha256: str,
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    if not path.is_file():
        raise BoundedDeepLoopError("final_manifest_missing", "completed receipt chain has no final manifest")
    try:
        manifest = read_json(path)
    except Exception as exc:
        raise BoundedDeepLoopError("final_manifest_corrupt", "final manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise BoundedDeepLoopError("final_manifest_corrupt", "final manifest root must be an object")
    if manifest.get("closure_run_id") != run_id or manifest.get("input_sha256") != input_sha256:
        raise BoundedDeepLoopError("final_manifest_binding_drift", "final manifest run/input binding drift")
    if manifest.get("stage_receipts") != receipts:
        raise BoundedDeepLoopError("final_manifest_receipt_drift", "final manifest receipt chain drift")
    _validate_contract(manifest)
    return manifest


def _validate_contract(payload: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise BoundedDeepLoopError("validator_unavailable", "project-local jsonschema is required") from exc
    schema = json.loads(bounded_deep_loop_schema_path().read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        detail = "; ".join(f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors[:8])
        raise BoundedDeepLoopError("contract_validation_failed", detail)


def _checkpoint(
    fixture: dict[str, Any],
    run_id: str,
    input_sha256: str,
    receipts: list[dict[str, Any]],
    *,
    completed: bool,
) -> dict[str, Any]:
    return {
        "schema": "question-research-bounded-deep-loop-checkpoint.v1",
        "contract_version": CONTRACT_VERSION,
        "closure_run_id": run_id,
        "fixture_id": fixture["fixture_id"],
        "input_sha256": input_sha256,
        "receipts": receipts,
        "completed_stages": [item["stage_id"] for item in receipts],
        "resume_from": None if completed or len(receipts) == len(STAGES) else STAGES[len(receipts)],
        "execution_status": "complete" if completed else "in_progress",
        "updated_at": fixture["observed_at"],
    }


def _stage_research_state(stage_id: str, artifact: dict[str, Any]) -> str:
    if stage_id == "guarded_synthesis":
        return str(artifact.get("status") or "blocked")
    if stage_id == "article_brief":
        return str((artifact.get("review_packet") or {}).get("status") or "pending_human_review")
    return "candidate_only"


def _result(run_dir: Path, manifest: dict[str, Any], *, reused: bool, finalized: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "execution_status": manifest["execution_status"],
        "research_status": manifest["research_status"],
        "closure_run_id": manifest["closure_run_id"],
        "run_dir": str(run_dir),
        "manifest_path": str(run_dir / "bounded-deep-loop.v1.json"),
        "manifest_sha256": _sha256((run_dir / "bounded-deep-loop.v1.json").read_bytes()),
        "completed_stages": [item["stage_id"] for item in manifest["stage_receipts"]],
        "resume_from": None,
        "search_stop_reason": manifest["search_stop_reason"],
        "finalization_authorized": bool(manifest["finalization_authorized"]),
        "reused": reused,
        "finalized": finalized,
        "truth_dimensions": manifest["truth_dimensions"],
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
