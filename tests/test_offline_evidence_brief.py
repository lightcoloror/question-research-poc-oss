from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from question_research_poc.bounded_deep_loop import BoundedDeepLoopError
from question_research_poc.offline_evidence_brief import DELIVERABLES, run_offline_evidence_brief


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "bounded-deep-loop"
READINESS = FIXTURE_ROOT / "synthetic-readiness-question.v1.json"
INSUFFICIENT = FIXTURE_ROOT / "synthetic-insufficient-evidence.v1.json"
INSURANCE = FIXTURE_ROOT / "deidentified-public-insurance-archive.v1.json"
RESEARCH_OUTPUT_SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "research-output.v1.schema.json").read_text(encoding="utf-8")
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, value: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _deliverable(result: dict, name: str) -> dict:
    return _load(Path(result["run_dir"]) / "deliverables" / name)


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.json"))
    }


def test_projection_uses_shared_packaged_schema_resolver(tmp_path, monkeypatch):
    import question_research_poc.offline_evidence_brief as module

    schema = tmp_path / "packaged-schema.json"
    schema.write_text('{"type":"object","required":["packaged_marker"]}', encoding="utf-8")
    monkeypatch.setattr(module, "research_output_schema_path", lambda: schema)
    module._validate_research_output({"packaged_marker": True})
    with pytest.raises(BoundedDeepLoopError) as error:
        module._validate_research_output({})
    assert error.value.code == "evidence_bundle_contract_invalid"


def test_one_command_projects_all_candidate_only_deliverables(tmp_path: Path) -> None:
    result = run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-pack-complete-001")
    assert result["projection_status"] == "complete_candidate_only"
    assert result["finalization_authorized"] is False
    assert {item["name"] for item in result["deliverables"]} == set(DELIVERABLES)

    bundle = _deliverable(result, "evidence-bundle.v1.json")
    jsonschema.Draft202012Validator(RESEARCH_OUTPUT_SCHEMA).validate(bundle)
    assert bundle["review_status"]["overall"] == "candidate"
    assert bundle["completeness"]["ready_for_answer"] is False
    assert bundle["guarded_final_answer"]["status"] == "blocked"
    assert bundle["provenance"]["model_memory_used_as_evidence"] is False

    brief = _deliverable(result, "content-brief.v1.json")
    packet = _deliverable(result, "review-packet.v1.json")
    assert brief["status"] == "candidate_only"
    assert brief["mode"] == "draft_only"
    assert packet["status"] == "pending_human_review"
    assert packet["authority"]["publish_authorized"] is False


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (READINESS, "candidate_for_human_review"),
        (INSUFFICIENT, "blocked_insufficient_evidence"),
        (INSURANCE, "candidate_for_human_review"),
    ],
)
def test_three_safe_fixtures_run_offline(fixture: Path, expected: str, tmp_path: Path) -> None:
    result = run_offline_evidence_brief(
        fixture,
        tmp_path,
        closure_run_id=f"offline-{fixture.stem[:28]}-001",
    )
    assert result["research_status"] == expected
    pack = _load(Path(result["manifest_path"]))
    assert pack["artifact_state"] == "candidate_only"
    assert pack["boundaries"]["network_called"] is False
    assert pack["boundaries"]["provider_called"] is False


def test_deidentified_insurance_fixture_preserves_wcf_archive_metadata(tmp_path: Path) -> None:
    result = run_offline_evidence_brief(INSURANCE, tmp_path, closure_run_id="offline-insurance-wcf-001")
    bundle = _deliverable(result, "evidence-bundle.v1.json")
    assert {source["provenance"]["note_fields"]["archive_contract"] for source in bundle["sources"]} == {
        "web-content-fetcher.evidence_archive.v1"
    }
    assert all(source["archive_path"].startswith("archives/deidentified-insurance/") for source in bundle["sources"])
    assert all(source["hash"]["status"] == "verified" for source in bundle["sources"])


def test_double_run_is_byte_stable(tmp_path: Path) -> None:
    first = run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-idempotent-001")
    run_dir = Path(first["run_dir"])
    before = _tree_hashes(run_dir)
    second = run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-idempotent-001")
    assert second["reused"] is True
    assert _tree_hashes(run_dir) == before
    assert second["manifest_sha256"] == first["manifest_sha256"]


def test_core_and_projection_crashes_resume_without_rewriting_receipts(tmp_path: Path) -> None:
    with pytest.raises(BoundedDeepLoopError) as core_crash:
        run_offline_evidence_brief(
            READINESS,
            tmp_path,
            closure_run_id="offline-core-crash-001",
            core_crash_after="evidence_analysis",
        )
    assert core_crash.value.code == "synthetic_crash_injected"
    core_receipt = tmp_path / "offline-core-crash-001" / "receipts" / "03-evidence_analysis.json"
    core_hash = hashlib.sha256(core_receipt.read_bytes()).hexdigest()
    resumed = run_offline_evidence_brief(
        READINESS,
        tmp_path,
        closure_run_id="offline-core-crash-001",
        resume=True,
    )
    assert resumed["execution_status"] == "complete"
    assert hashlib.sha256(core_receipt.read_bytes()).hexdigest() == core_hash

    with pytest.raises(BoundedDeepLoopError) as projection_crash:
        run_offline_evidence_brief(
            READINESS,
            tmp_path,
            closure_run_id="offline-projection-crash-001",
            projection_crash_after="deliverables",
        )
    assert projection_crash.value.code == "synthetic_projection_crash_injected"
    with pytest.raises(BoundedDeepLoopError) as no_resume:
        run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-projection-crash-001")
    assert no_resume.value.code == "projection_resume_required"
    recovered = run_offline_evidence_brief(
        READINESS,
        tmp_path,
        closure_run_id="offline-projection-crash-001",
        resume=True,
    )
    assert recovered["projection_status"] == "complete_candidate_only"


def test_unversioned_fixture_is_migrated_without_semantic_upgrade(tmp_path: Path) -> None:
    result = run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-legacy-migration-001")
    migration = _load(Path(result["manifest_path"]))["input_contract_migration"]
    assert migration == {
        "applied": True,
        "from": "unversioned-legacy-fixture",
        "to": "1.0.0",
        "semantic_change": False,
    }


def test_tamper_missing_citation_and_archive_path_escape_fail_closed(tmp_path: Path) -> None:
    result = run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-tamper-001")
    bundle_path = Path(result["run_dir"]) / "deliverables" / "evidence-bundle.v1.json"
    payload = _load(bundle_path)
    payload["guarded_final_answer"]["status"] = "verified"
    bundle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(BoundedDeepLoopError) as drift:
        run_offline_evidence_brief(READINESS, tmp_path, closure_run_id="offline-tamper-001")
    assert drift.value.code == "projection_artifact_drift"

    missing = _load(READINESS)
    missing["evidence"][0]["text"] = ""
    missing_path = _write(tmp_path, missing, "missing-citation.json")
    with pytest.raises(BoundedDeepLoopError) as citation:
        run_offline_evidence_brief(missing_path, tmp_path / "missing", closure_run_id="offline-missing-citation-001")
    assert citation.value.code == "evidence_citation_missing"

    escaped = _load(INSURANCE)
    escaped["sources"][0]["archive_path"] = "../../private.md"
    escaped_path = _write(tmp_path, escaped, "path-escape.json")
    with pytest.raises(BoundedDeepLoopError) as path_escape:
        run_offline_evidence_brief(escaped_path, tmp_path / "escape", closure_run_id="offline-path-escape-001")
    assert path_escape.value.code == "source_archive_path_escape"


def test_stale_conflict_and_model_inference_never_become_final_fact(tmp_path: Path) -> None:
    stale = _load(READINESS)
    for source in stale["sources"]:
        source["freshness"] = "stale"
    stale_path = _write(tmp_path, stale, "stale.json")
    stale_result = run_offline_evidence_brief(stale_path, tmp_path / "stale", closure_run_id="offline-stale-001")
    stale_bundle = _deliverable(stale_result, "evidence-bundle.v1.json")
    assert stale_bundle["guarded_final_answer"]["status"] == "blocked"
    assert stale_bundle["completeness"]["ready_for_answer"] is False

    conflict_result = run_offline_evidence_brief(INSURANCE, tmp_path / "conflict", closure_run_id="offline-conflict-001")
    conflict_packet = _deliverable(conflict_result, "review-packet.v1.json")
    assert conflict_packet["contradictions"]
    assert conflict_packet["status"] == "pending_human_review"

    inference = _load(READINESS)
    row = next(item for item in inference["evidence"] if item["evidence_type"] == "agent_inference")
    row["status"] = "verified"
    row["review_status"] = "reviewed"
    inference_path = _write(tmp_path, inference, "model-inference.json")
    inference_result = run_offline_evidence_brief(
        inference_path,
        tmp_path / "inference",
        closure_run_id="offline-model-inference-001",
    )
    bundle = _deliverable(inference_result, "evidence-bundle.v1.json")
    projected = next(item for item in bundle["evidence"] if item["evidence_id"] == row["evidence_id"])
    assert projected["ai_synthesis"] is True
    assert projected["evidence_status"] == "candidate"
    assert bundle["guarded_final_answer"]["status"] == "blocked"
