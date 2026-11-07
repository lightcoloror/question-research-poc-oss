from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from question_research_poc.bounded_deep_loop import (
    BoundedDeepLoopError,
    run_bounded_deep_loop,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bounded-deep-loop" / "synthetic-readiness-question.v1.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write_fixture(tmp_path: Path, payload: dict, name: str = "fixture.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _artifact(run_dir: Path, name: str) -> dict:
    return json.loads((run_dir / "artifacts" / name).read_text(encoding="utf-8"))


def test_complete_loop_is_bounded_guarded_and_candidate_only(tmp_path: Path) -> None:
    result = run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-complete-001")
    run_dir = Path(result["run_dir"])
    intake = _artifact(run_dir, "01-intake.json")
    admission = _artifact(run_dir, "02-source_admission.json")
    analysis = _artifact(run_dir, "03-evidence_analysis.json")
    brief = _artifact(run_dir, "05-article_brief.json")

    assert result["execution_status"] == "complete"
    assert result["research_status"] == "candidate_for_human_review"
    assert result["finalization_authorized"] is False
    assert [item["subquestion_id"] for item in intake["selected_subquestions"]] == [
        "sq-measurement-policy",
        "sq-measurement-noise",
        "sq-single-reading",
    ]
    assert intake["open_ended_expansion"] is False
    assert admission["duplicate_sources"] == [
        {"source_id": "src-protocol-duplicate", "duplicate_of": "src-protocol"}
    ]
    assert analysis["classification_counts"] == {
        "source_fact": 3,
        "source_claim": 1,
        "agent_inference": 1,
        "unknown": 1,
        "contradicted": 1,
    }
    assert analysis["search_continuation_authorized"] is False
    assert brief["mode"] == "draft_only"
    assert brief["authority"] == {
        "execution_authorized": False,
        "publish_authorized": False,
        "external_write_authorized": False,
    }
    assert brief["review_packet"]["status"] == "pending_human_review"
    assert result["truth_dimensions"]["fresh_e2e_pass"] is True
    assert result["truth_dimensions"]["real_usage_proof"] is False
    assert result["truth_dimensions"]["current_online"] is False


def test_double_run_is_byte_stable_and_reuses_receipts(tmp_path: Path) -> None:
    first = run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-idempotent-001")
    run_dir = Path(first["run_dir"])
    before = {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run_dir.rglob("*.json")
    }
    second = run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-idempotent-001")
    after = {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run_dir.rglob("*.json")
    }
    assert second["reused"] is True
    assert before == after
    assert first["manifest_sha256"] == second["manifest_sha256"]


def test_crash_after_receipt_recovers_without_replaying_prior_stage(tmp_path: Path) -> None:
    with pytest.raises(BoundedDeepLoopError, match="receipt persisted") as caught:
        run_bounded_deep_loop(
            FIXTURE,
            tmp_path,
            closure_run_id="bounded-crash-001",
            crash_after="source_admission",
        )
    assert caught.value.code == "synthetic_crash_injected"
    run_dir = tmp_path / "bounded-crash-001"
    receipt_hash = hashlib.sha256((run_dir / "receipts" / "02-source_admission.json").read_bytes()).hexdigest()

    resumed = run_bounded_deep_loop(
        FIXTURE,
        tmp_path,
        closure_run_id="bounded-crash-001",
        resume=True,
    )
    assert resumed["execution_status"] == "complete"
    assert hashlib.sha256((run_dir / "receipts" / "02-source_admission.json").read_bytes()).hexdigest() == receipt_hash
    checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["resume_from"] is None
    assert checkpoint["execution_status"] == "complete"


def test_crash_after_final_receipt_rebuilds_only_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(BoundedDeepLoopError) as caught:
        run_bounded_deep_loop(
            FIXTURE,
            tmp_path,
            closure_run_id="bounded-final-crash-001",
            crash_after="article_brief",
        )
    assert caught.value.code == "synthetic_crash_injected"
    run_dir = tmp_path / "bounded-final-crash-001"
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (run_dir / "receipts").glob("*.json")
    }
    assert not (run_dir / "bounded-deep-loop.v1.json").exists()
    resumed = run_bounded_deep_loop(
        FIXTURE,
        tmp_path,
        closure_run_id="bounded-final-crash-001",
        resume=True,
    )
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (run_dir / "receipts").glob("*.json")
    }
    assert resumed["execution_status"] == "complete"
    assert before == after


def test_partial_run_requires_resume_and_rejects_early_finalize(tmp_path: Path) -> None:
    paused = run_bounded_deep_loop(
        FIXTURE,
        tmp_path,
        closure_run_id="bounded-partial-001",
        stop_after="intake",
    )
    assert paused["resume_from"] == "source_admission"
    with pytest.raises(BoundedDeepLoopError) as no_resume:
        run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-partial-001")
    assert no_resume.value.code == "resume_required"
    with pytest.raises(BoundedDeepLoopError) as early:
        run_bounded_deep_loop(
            FIXTURE,
            tmp_path,
            closure_run_id="bounded-partial-001",
            request_finalize=True,
        )
    assert early.value.code == "early_finalize_rejected"


def test_corrupt_receipt_and_out_of_order_chain_fail_closed(tmp_path: Path) -> None:
    complete = run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-receipt-drift-001")
    receipt_path = Path(complete["run_dir"]) / "receipts" / "03-evidence_analysis.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["stage_index"] = 9
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    with pytest.raises(BoundedDeepLoopError) as drift:
        run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-receipt-drift-001")
    assert drift.value.code == "receipt_binding_drift"

    other_root = tmp_path / "order"
    complete = run_bounded_deep_loop(FIXTURE, other_root, closure_run_id="bounded-order-001")
    run_dir = Path(complete["run_dir"])
    (run_dir / "receipts" / "02-source_admission.json").unlink()
    with pytest.raises(BoundedDeepLoopError) as order:
        run_bounded_deep_loop(FIXTURE, other_root, closure_run_id="bounded-order-001", resume=True)
    assert order.value.code == "receipt_order_invalid"


def test_artifact_hash_drift_fails_closed(tmp_path: Path) -> None:
    complete = run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-artifact-drift-001")
    artifact_path = Path(complete["run_dir"]) / "artifacts" / "04-guarded_synthesis.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["finalization_authorized"] = True
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    with pytest.raises(BoundedDeepLoopError) as drift:
        run_bounded_deep_loop(FIXTURE, tmp_path, closure_run_id="bounded-artifact-drift-001")
    assert drift.value.code == "receipt_artifact_hash_drift"


def test_source_hash_drift_is_not_admitted_or_finalized(tmp_path: Path) -> None:
    fixture = _load_fixture()
    for source in fixture["sources"]:
        source["content_sha256"] = "0" * 64
    path = _write_fixture(tmp_path, fixture, "hash-drift.json")
    result = run_bounded_deep_loop(path, tmp_path / "runs", closure_run_id="bounded-source-drift-001")
    run_dir = Path(result["run_dir"])
    admission = _artifact(run_dir, "02-source_admission.json")
    synthesis = _artifact(run_dir, "04-guarded_synthesis.json")
    assert admission["admitted_sources"] == []
    assert len(admission["blockers"]) == 4
    assert result["research_status"] == "blocked_insufficient_evidence"
    assert result["search_stop_reason"] == "source_integrity_blocked"
    assert synthesis["finalization_authorized"] is False


def test_stale_sources_and_insufficient_evidence_fail_closed(tmp_path: Path) -> None:
    fixture = _load_fixture()
    for source in fixture["sources"]:
        source["freshness"] = "stale"
    path = _write_fixture(tmp_path, fixture, "stale.json")
    result = run_bounded_deep_loop(path, tmp_path / "runs", closure_run_id="bounded-stale-001")
    analysis = _artifact(Path(result["run_dir"]), "03-evidence_analysis.json")
    assert result["research_status"] == "blocked_insufficient_evidence"
    assert result["search_stop_reason"] == "insufficient_evidence"
    assert {item["evidence_status"] for item in analysis["claims"]} == {"unknown"}


def test_budget_exhaustion_stops_expansion_without_silent_fallback(tmp_path: Path) -> None:
    fixture = _load_fixture()
    fixture["budgets"]["max_tokens"] = 300
    path = _write_fixture(tmp_path, fixture, "budget.json")
    result = run_bounded_deep_loop(path, tmp_path / "runs", closure_run_id="bounded-budget-001")
    run_dir = Path(result["run_dir"])
    admission = _artifact(run_dir, "02-source_admission.json")
    assert result["search_stop_reason"] == "budget_exhausted"
    assert any(item["reason"] == "token_budget" for item in admission["excluded_sources"])
    manifest = json.loads((run_dir / "bounded-deep-loop.v1.json").read_text(encoding="utf-8"))
    assert manifest["boundaries"]["silent_fallback_used"] is False
    assert manifest["boundaries"]["network_called"] is False


def test_fixture_reference_and_evidence_type_errors_are_structured(tmp_path: Path) -> None:
    fixture = _load_fixture()
    fixture["evidence"][0]["source_id"] = "missing-source"
    missing_path = _write_fixture(tmp_path, fixture, "missing-ref.json")
    with pytest.raises(BoundedDeepLoopError) as missing:
        run_bounded_deep_loop(missing_path, tmp_path / "runs", closure_run_id="bounded-missing-ref-001")
    assert missing.value.code == "fixture_reference_missing"

    fixture = _load_fixture()
    fixture["evidence"][0]["evidence_type"] = "model_memory"
    type_path = _write_fixture(tmp_path, fixture, "bad-type.json")
    with pytest.raises(BoundedDeepLoopError) as evidence_type:
        run_bounded_deep_loop(type_path, tmp_path / "runs", closure_run_id="bounded-bad-type-001")
    assert evidence_type.value.code == "fixture_evidence_type_invalid"
