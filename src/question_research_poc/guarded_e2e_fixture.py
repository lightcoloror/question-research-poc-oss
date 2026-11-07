from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .completeness_audit import audit_research_completeness
from .final_answer import export_final_answer
from .orchestrator import add_claim, add_evidence, add_source, init_project, list_records, review_evidence, review_source
from .storage import read_json, write_json

FIXTURE_SCHEMA = "question_research_guarded_e2e_fixture.v1"
FIXTURE_STATE_SCHEMA_VERSION = 2
FIXTURE_STATE_FILE = "guarded-e2e-fixture-state.json"
FIXTURE_MARKER = "qrp_guarded_e2e_fixture_v1"
FIXTURE_QUESTION = "本地合成 guarded research E2E 是否成立？"
FIXTURE_SOURCE_TITLE = "QRP guarded E2E synthetic source"
FIXTURE_CLAIM_TEXT = "最终答案必须在来源和支持证据显式审核后才可导出。"
FIXTURE_SUPPORT_NOTE = "Synthetic support: reviewed support evidence unlocks final readiness."
FIXTURE_REJECTED_NOTE = "Synthetic rejected: this overbroad candidate must not enter the final answer."

FIXTURE_STATE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema", "schema_version", "stages", "blocked_export_observed", "receipts"],
    "properties": {
        "schema": {"const": FIXTURE_SCHEMA},
        "schema_version": {"type": "integer", "minimum": 1},
        "stages": {"type": "object"},
        "blocked_export_observed": {"type": "boolean"},
        "receipts": {"type": "array", "items": {"type": "object", "required": ["id", "kind", "record_id"]}},
        "evidence_hashes": {"type": "object"},
        "last_completed_stage": {"type": "string"},
        "recovered_from_corrupt_state": {"type": "boolean"},
        "migrations": {"type": "array", "items": {"type": "string"}},
        "hash_drift_detected": {"type": "array"},
    },
}

_STAGE_ORDER = ["intake", "evidence", "blocked", "review", "final"]
_STAGE_SET = set(_STAGE_ORDER)


def run_guarded_e2e_fixture(
    root: str | Path,
    *,
    reviewer: str = "guarded-e2e-fixture",
    stop_after: str | None = None,
) -> dict[str, Any]:
    """Run a fully local, synthetic, recoverable guarded research E2E fixture."""
    if stop_after is not None and stop_after not in _STAGE_SET:
        raise ValueError(f"stop_after must be one of: {', '.join(_STAGE_ORDER)}")

    project_root = Path(root)
    state = _read_state(project_root)
    events: list[dict[str, Any]] = []

    if not (project_root / "research.json").exists():
        project = init_project(project_root, FIXTURE_QUESTION)
        events.append(_event("intake", "initialized_project", project.id))
    else:
        events.append(_event("intake", "reused_project", "research.json"))
    _write_stage(project_root, state, "intake", events)
    if stop_after == "intake":
        return _payload(project_root, state, events, status="stopped_after_intake")

    source = _ensure_source(project_root, state, events)
    claim = _ensure_claim(project_root, state, events)
    support = _ensure_evidence(
        project_root,
        state,
        evidence_key="support",
        claim_id=str(claim["id"]),
        source_id=str(source["id"]),
        quote_or_note=FIXTURE_SUPPORT_NOTE,
        relation="supports",
        events=events,
    )
    rejected = _ensure_evidence(
        project_root,
        state,
        evidence_key="rejected",
        claim_id=str(claim["id"]),
        source_id=str(source["id"]),
        quote_or_note=FIXTURE_REJECTED_NOTE,
        relation="supports",
        events=events,
    )
    evidence_ids = {"source_id": source["id"], "claim_id": claim["id"], "support_evidence_id": support["id"], "rejected_evidence_id": rejected["id"]}
    drift = _detect_evidence_hash_drift(state, {"support": support, "rejected": rejected})
    if drift:
        state["hash_drift_detected"] = drift
        events.append(_event("evidence", "detected_evidence_hash_drift", ",".join(item["evidence_key"] for item in drift)))
        _write_stage(project_root, state, "evidence", events, ids=evidence_ids)
        return _payload(project_root, state, events, status="evidence_hash_drift_detected")
    state.pop("hash_drift_detected", None)
    _record_evidence_hashes(state, {"support": support, "rejected": rejected})
    _write_stage(project_root, state, "evidence", events, ids=evidence_ids)
    if stop_after == "evidence":
        return _payload(project_root, state, events, status="stopped_after_evidence")

    blocked = export_final_answer(project_root)
    if not blocked.get("ok") and blocked.get("blocked"):
        state["blocked_export_observed"] = True
        events.append(_event("blocked", "observed_blocked_export", ",".join(blocked.get("blocking_gates", []))))
    elif state.get("blocked_export_observed"):
        events.append(_event("blocked", "reused_prior_blocked_observation", FIXTURE_STATE_FILE))
    else:
        events.append(_event("blocked", "blocked_observation_unavailable", "project_already_reviewed"))
    _write_stage(project_root, state, "blocked", events, ids={"blocked_export_observed": bool(state.get("blocked_export_observed"))})
    if stop_after == "blocked":
        return _payload(project_root, state, events, status="stopped_after_blocked")

    source = _review_source_if_needed(project_root, state, str(source["id"]), reviewer, events)
    support = _review_evidence_if_needed(project_root, state, str(support["id"]), status="verified", relation="supports", confidence="high", reviewer=reviewer, notes="Fixture accepted support evidence.", events=events)
    rejected = _review_evidence_if_needed(project_root, state, str(rejected["id"]), status="rejected", relation="supports", confidence="low", reviewer=reviewer, notes="Fixture rejected overbroad synthetic evidence.", events=events)
    _write_stage(project_root, state, "review", events, ids={"source_id": source["id"], "support_evidence_id": support["id"], "rejected_evidence_id": rejected["id"]})
    if stop_after == "review":
        return _payload(project_root, state, events, status="stopped_after_review")

    audit = audit_research_completeness(project_root)
    final = export_final_answer(project_root)
    _write_stage(
        project_root,
        state,
        "final",
        events,
        ids={
            "ready_for_answer": bool(audit.get("ready_for_answer")),
            "final_export_ok": bool(final.get("ok")),
            "final_markdown": final.get("files", {}).get("markdown", "") if isinstance(final.get("files"), dict) else "",
        },
    )
    return _payload(project_root, state, events, status="complete", audit=audit, final_export=final)


def _ensure_source(project_root: Path, state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    expected_id = _state_id(state, "evidence", "source_id") or _state_id(state, "review", "source_id")
    existing = _find_record(list_records(project_root, "sources"), id=expected_id) if expected_id else None
    existing = existing or _find_record(list_records(project_root, "sources"), title=FIXTURE_SOURCE_TITLE)
    if existing:
        events.append(_event("evidence", "reused_source", str(existing.get("id", ""))))
        _record_receipt(state, "source", str(existing.get("id", "")), "present")
        return existing
    source = add_source(project_root, title=FIXTURE_SOURCE_TITLE, path="local://qrp/guarded-e2e/synthetic-source", source_type="local_fixture", quality="unknown", notes=FIXTURE_MARKER)
    events.append(_event("evidence", "created_source", source.id))
    _record_receipt(state, "source", source.id, "created")
    return _find_record(list_records(project_root, "sources"), id=source.id) or {"id": source.id, "title": source.title, "quality": source.quality}


def _ensure_claim(project_root: Path, state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    expected_id = _state_id(state, "evidence", "claim_id")
    existing = _find_record(list_records(project_root, "claims"), id=expected_id) if expected_id else None
    existing = existing or _find_record(list_records(project_root, "claims"), text=FIXTURE_CLAIM_TEXT)
    if existing:
        events.append(_event("evidence", "reused_claim", str(existing.get("id", ""))))
        _record_receipt(state, "claim", str(existing.get("id", "")), "present")
        return existing
    claim = add_claim(project_root, text=FIXTURE_CLAIM_TEXT, notes=FIXTURE_MARKER)
    events.append(_event("evidence", "created_claim", claim.id))
    _record_receipt(state, "claim", claim.id, "created")
    return _find_record(list_records(project_root, "claims"), id=claim.id) or {"id": claim.id, "text": claim.text}


def _ensure_evidence(project_root: Path, state: dict[str, Any], *, evidence_key: str, claim_id: str, source_id: str, quote_or_note: str, relation: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    id_key = f"{evidence_key}_evidence_id"
    expected_id = _state_id(state, "evidence", id_key) or _state_id(state, "review", id_key)
    existing = _find_record(list_records(project_root, "evidence"), id=expected_id) if expected_id else None
    existing = existing or _find_record(list_records(project_root, "evidence"), claim_id=claim_id, source_id=source_id, quote_or_note=quote_or_note)
    if existing:
        events.append(_event("evidence", "reused_evidence", str(existing.get("id", ""))))
        _record_receipt(state, "evidence", str(existing.get("id", "")), "present")
        return existing
    evidence = add_evidence(project_root, claim_id=claim_id, source_id=source_id, quote_or_note=quote_or_note, relation=relation, confidence="medium", notes=FIXTURE_MARKER)
    events.append(_event("evidence", "created_evidence", evidence.id))
    _record_receipt(state, "evidence", evidence.id, "created")
    return _find_record(list_records(project_root, "evidence"), id=evidence.id) or {"id": evidence.id, "claim_id": claim_id, "source_id": source_id, "quote_or_note": quote_or_note, "relation": relation}


def _review_source_if_needed(project_root: Path, state: dict[str, Any], source_id: str, reviewer: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    source = _find_record(list_records(project_root, "sources"), id=source_id)
    if source and source.get("quality") == "good":
        events.append(_event("review", "reused_source_review", source_id))
        _record_receipt(state, "source_review", source_id, "good")
        return source
    review_source(project_root, source_id=source_id, quality="good", reason="Fixture reviewed local synthetic source.", reviewer=reviewer)
    events.append(_event("review", "reviewed_source", source_id))
    _record_receipt(state, "source_review", source_id, "good")
    return _find_record(list_records(project_root, "sources"), id=source_id) or {"id": source_id, "quality": "good"}


def _review_evidence_if_needed(
    project_root: Path,
    state: dict[str, Any],
    evidence_id: str,
    *,
    status: str,
    relation: str,
    confidence: str,
    reviewer: str,
    notes: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = _find_record(list_records(project_root, "evidence"), id=evidence_id)
    if evidence and evidence.get("status") == status and evidence.get("relation") == relation:
        events.append(_event("review", f"reused_{status}_evidence", evidence_id))
        _record_receipt(state, "evidence_review", evidence_id, status)
        return evidence
    result = review_evidence(project_root, evidence_id=evidence_id, status=status, relation=relation, confidence=confidence, notes=notes, reviewer=reviewer)
    events.append(_event("review", f"reviewed_{status}_evidence", evidence_id))
    _record_receipt(state, "evidence_review", evidence_id, status)
    return result["evidence"]


def _payload(
    project_root: Path,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    status: str,
    audit: dict[str, Any] | None = None,
    final_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actual_audit = audit or audit_research_completeness(project_root)
    drift = state.get("hash_drift_detected") if isinstance(state.get("hash_drift_detected"), list) else []
    return {
        "ok": status == "complete" and bool(actual_audit.get("ready_for_answer")) and not drift,
        "schema": FIXTURE_SCHEMA,
        "schema_version": state.get("schema_version", FIXTURE_STATE_SCHEMA_VERSION),
        "status": status,
        "root": str(project_root),
        "state_file": str(project_root / FIXTURE_STATE_FILE),
        "last_completed_stage": state.get("last_completed_stage", ""),
        "blocked_export_observed": bool(state.get("blocked_export_observed")),
        "recovered_from_corrupt_state": bool(state.get("recovered_from_corrupt_state")),
        "migrations": state.get("migrations", []),
        "receipt_count": len(state.get("receipts", [])) if isinstance(state.get("receipts"), list) else 0,
        "hash_drift_detected": drift,
        "audit": actual_audit,
        "final_export": final_export or {},
        "events": events,
        "external_services": {"ai_research_workflow_9082": "stopped_by_design", "http_started": False, "external_api_called": False},
    }


def _read_state(project_root: Path) -> dict[str, Any]:
    path = project_root / FIXTURE_STATE_FILE
    if not path.exists():
        return _default_state()
    try:
        data = read_json(path)
    except Exception:
        return _default_state(recovered_from_corrupt_state=True, migrations=["corrupt_state_reinitialized"])
    if not isinstance(data, dict):
        return _default_state(recovered_from_corrupt_state=True, migrations=["non_object_state_reinitialized"])
    return _migrate_state(data)


def _default_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema": FIXTURE_SCHEMA,
        "schema_version": FIXTURE_STATE_SCHEMA_VERSION,
        "stages": {},
        "blocked_export_observed": False,
        "receipts": [],
        "evidence_hashes": {},
        "migrations": [],
    }
    state.update(overrides)
    return state


def _migrate_state(data: dict[str, Any]) -> dict[str, Any]:
    state = _default_state()
    migrations: list[str] = []
    if data.get("schema") != FIXTURE_SCHEMA:
        migrations.append(f"schema:{data.get('schema', 'missing')}->{FIXTURE_SCHEMA}")
    if data.get("schema_version") != FIXTURE_STATE_SCHEMA_VERSION:
        migrations.append(f"schema_version:{data.get('schema_version', 'missing')}->{FIXTURE_STATE_SCHEMA_VERSION}")
    raw_stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    for stage, payload in raw_stages.items():
        if stage in _STAGE_SET and isinstance(payload, dict):
            state["stages"][stage] = payload
    legacy_stage = data.get("stage") or data.get("last_completed_stage")
    if isinstance(legacy_stage, str) and legacy_stage in _STAGE_SET and legacy_stage not in state["stages"]:
        state["stages"][legacy_stage] = {"completed": True, "ids": {}}
        migrations.append("legacy_stage_promoted")
    if isinstance(data.get("blocked_export_observed"), bool):
        state["blocked_export_observed"] = data["blocked_export_observed"]
    state["receipts"] = _dedupe_receipts(data.get("receipts", []))
    if isinstance(data.get("evidence_hashes"), dict):
        state["evidence_hashes"] = {str(key): str(value) for key, value in data["evidence_hashes"].items()}
    if isinstance(data.get("last_completed_stage"), str):
        state["last_completed_stage"] = data["last_completed_stage"]
    elif legacy_stage in _STAGE_SET:
        state["last_completed_stage"] = legacy_stage
    if data.get("recovered_from_corrupt_state"):
        state["recovered_from_corrupt_state"] = True
    prior_migrations = data.get("migrations") if isinstance(data.get("migrations"), list) else []
    state["migrations"] = list(dict.fromkeys([str(item) for item in prior_migrations] + migrations))
    return state


def _write_stage(project_root: Path, state: dict[str, Any], stage: str, events: list[dict[str, Any]], *, ids: dict[str, Any] | None = None) -> None:
    state["schema"] = FIXTURE_SCHEMA
    state["schema_version"] = FIXTURE_STATE_SCHEMA_VERSION
    state.setdefault("stages", {})[stage] = {"completed": True, "ids": ids or {}}
    state["last_completed_stage"] = stage
    state["event_count"] = len(events)
    state["receipts"] = _dedupe_receipts(state.get("receipts", []))
    write_json(project_root / FIXTURE_STATE_FILE, state)


def _record_receipt(state: dict[str, Any], kind: str, record_id: str, status: str) -> None:
    if not record_id:
        return
    receipt = {"id": f"{kind}:{record_id}:{status}", "kind": kind, "record_id": record_id, "status": status}
    state.setdefault("receipts", []).append(receipt)
    state["receipts"] = _dedupe_receipts(state.get("receipts", []))


def _dedupe_receipts(raw_receipts: Any) -> list[dict[str, str]]:
    deduped: dict[str, dict[str, str]] = {}
    if not isinstance(raw_receipts, list):
        return []
    for receipt in raw_receipts:
        if not isinstance(receipt, dict):
            continue
        receipt_id = str(receipt.get("id") or "")
        kind = str(receipt.get("kind") or "")
        record_id = str(receipt.get("record_id") or "")
        status = str(receipt.get("status") or "")
        if not receipt_id and kind and record_id:
            receipt_id = f"{kind}:{record_id}:{status}"
        if receipt_id:
            deduped[receipt_id] = {"id": receipt_id, "kind": kind, "record_id": record_id, "status": status}
    return list(deduped.values())


def _record_evidence_hashes(state: dict[str, Any], evidence_by_key: dict[str, dict[str, Any]]) -> None:
    hashes = state.setdefault("evidence_hashes", {})
    for key, evidence in evidence_by_key.items():
        hashes[key] = _evidence_hash(evidence)


def _detect_evidence_hash_drift(state: dict[str, Any], evidence_by_key: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    expected = state.get("evidence_hashes") if isinstance(state.get("evidence_hashes"), dict) else {}
    drift: list[dict[str, str]] = []
    for key, evidence in evidence_by_key.items():
        expected_hash = str(expected.get(key, ""))
        if not expected_hash:
            continue
        actual_hash = _evidence_hash(evidence)
        if actual_hash != expected_hash:
            drift.append({"evidence_key": key, "evidence_id": str(evidence.get("id", "")), "expected_hash": expected_hash, "actual_hash": actual_hash})
    return drift


def _evidence_hash(evidence: dict[str, Any]) -> str:
    payload = {
        "claim_id": str(evidence.get("claim_id", "")),
        "source_id": str(evidence.get("source_id", "")),
        "quote_or_note": str(evidence.get("quote_or_note", "")),
        "relation": str(evidence.get("relation", "")),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _state_id(state: dict[str, Any], stage: str, key: str) -> str:
    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    stage_payload = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    ids = stage_payload.get("ids") if isinstance(stage_payload.get("ids"), dict) else {}
    return str(ids.get(key, ""))


def _find_record(records: list[dict[str, Any]], **fields: str) -> dict[str, Any] | None:
    for record in records:
        if all(str(record.get(key, "")) == str(value) for key, value in fields.items()):
            return record
    return None


def _event(stage: str, action: str, ref: str) -> dict[str, str]:
    return {"stage": stage, "action": action, "ref": ref}