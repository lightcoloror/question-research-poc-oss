from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from model_provider_gateway.consent import build_consent_plan, consent_revision
from model_provider_gateway.execution import LiteLLMTransport
from model_provider_gateway.mock_server import mock_server
from model_provider_gateway.profile import build_profile
from model_provider_gateway.route import build_route_plan, route_revision
from question_research_poc import model_gateway_bridge
from question_research_poc.cli import main as cli_main
from question_research_poc.model_gateway_bridge import (
    run_gateway_embedding_candidate,
    run_gateway_model_assist,
)
from question_research_poc.orchestrator import add_claim, add_evidence, add_source, init_project
from research_workflow import model_gateway as arw_model_gateway


requires_semantic_arw = pytest.mark.skipif(
    not (
        hasattr(arw_model_gateway, "ModelGatewaySemanticIncompatible")
        and "visual_claim_assist" in getattr(arw_model_gateway, "SUPPORTED_TASKS", set())
    ),
    reason="published ARW install snapshot does not yet expose the semantic vision contract",
)


def _contracts(root: Path, *, capability: str = "text", calls: int = 12) -> tuple[dict, dict, dict]:
    if capability == "text":
        artifact = root / "synthetic-input.txt"
        artifact.write_text("Synthetic candidate material only.", encoding="utf-8")
        preset = "modelscope-glm-5-2"
    else:
        artifact = root / "synthetic-input.png"
        artifact.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
                "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
            )
        )
        preset = "siliconflow-glm-4-5v"
    profile = build_profile(
        preset,
        "env:MPG_SYNTHETIC_KEY",
        last_verified="2026-08-05T00:00:00+00:00",
        max_calls=calls,
        max_cost_usd=1.0,
        timeout_seconds=1,
    )
    route = build_route_plan("qrp-synthetic", capability, [profile], max_calls=calls, max_cost_usd=1.0)
    consent = build_consent_plan(
        route,
        [artifact],
        capability=capability,
        purpose="Produce a synthetic planning candidate for human review.",
        data_type="synthetic_research_fixture",
        max_calls=calls,
        max_cost_usd=1.0,
    )
    return profile, route, consent


def _project_with_truth(root: Path) -> dict[str, bytes]:
    init_project(root, "Can a model output become verified evidence?")
    source = add_source(root, title="Synthetic source", url="https://example.invalid/source", quality="unknown")
    claim = add_claim(root, text="Only reviewed evidence can support a final answer")
    add_evidence(root, claim_id=claim.id, source_id=source.id, quote_or_note="Candidate note only")
    return {name: (root / name).read_bytes() for name in ("sources.jsonl", "claims.jsonl", "evidence.jsonl")}


def _assert_truth_unchanged(root: Path, before: dict[str, bytes]) -> None:
    assert {name: (root / name).read_bytes() for name in before} == before


@requires_semantic_arw
def test_loopback_roundtrip_is_thin_candidate_only_and_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)
    receipt = project / "model-assist-receipts" / "explicit.json"
    ledger = project / "model-assist-receipts" / "ledger.json"
    with mock_server() as base_url:
        first = run_gateway_model_assist(
            project,
            profile=profile,
            route=route,
            consent=consent,
            purpose="planning",
            request_id="qrp-loopback",
            max_estimated_cost_usd=0.1,
            receipt_path=receipt,
            ledger_path=ledger,
            transport=LiteLLMTransport.loopback_stub(base_url),
            secret_resolver=lambda _ref: "synthetic-secret-never-log",
        )
    first_bytes = receipt.read_bytes()
    second = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=consent,
        purpose="planning",
        request_id="qrp-loopback",
        max_estimated_cost_usd=0.1,
        receipt_path=receipt,
        ledger_path=ledger,
    )

    assert first == second
    assert receipt.read_bytes() == first_bytes
    assert first["consumer_id"] == "qrp"
    assert first["task"] == "research_query"
    assert first["execution_result"]["schema"] == "model_provider_gateway.execution_result.v1"
    assert first["model_output_status"] == "candidate_only"
    assert first["research_truth_effect"] == "none"
    assert first["evidence_status_change"] == "none"
    assert first["automatic_fallback_allowed"] is False
    assert first["automatic_retry_allowed"] is False
    assert first["gateway_contract"]["compatibility_status"] == "verified"
    assert first["gateway_contract"]["commit_is_compatibility_gate"] is False
    assert first["gateway_contract"]["version_is_compatibility_gate"] is True
    assert first["gateway_contract"]["semantic_contract_sha256"] == model_gateway_bridge.EXPECTED_GATEWAY_SEMANTIC_CONTRACT_SHA256
    assert str(tmp_path) not in json.dumps(first)
    assert "synthetic-secret-never-log" not in json.dumps(first)
    _assert_truth_unchanged(project, before)


def test_qrp_accepts_the_versioned_content_hashed_arw_contract() -> None:
    contract = arw_model_gateway.consumer_contract_manifest()

    assert model_gateway_bridge._validate_arw_consumer_contract(contract) is contract
    assert contract["gateway"]["git_commit_role"] == "provenance_only"


@pytest.mark.parametrize("drift", ["hash", "package_version", "contract_version", "gateway_hash"])
def test_qrp_rejects_arw_contract_drift(drift: str) -> None:
    contract = copy.deepcopy(arw_model_gateway.consumer_contract_manifest())
    if drift == "package_version":
        contract["package_version"] = "0.2.0"
    elif drift == "contract_version":
        contract["contract_version"] = "2.0.0"
    elif drift == "gateway_hash":
        contract["gateway"]["semantic_contract_sha256"] = "0" * 64
    if drift != "hash":
        payload = dict(contract)
        payload.pop("contract_sha256", None)
        contract["contract_sha256"] = model_gateway_bridge._canonical_hash(payload)
    else:
        contract["contract_sha256"] = "0" * 64

    with pytest.raises(RuntimeError):
        model_gateway_bridge._validate_arw_consumer_contract(contract)


@pytest.mark.parametrize("tamper", ["request_replay", "fingerprint"])
@requires_semantic_arw
def test_model_receipt_is_bound_to_the_exact_qrp_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    project = tmp_path / tamper
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)
    with mock_server() as base_url:
        receipt = run_gateway_model_assist(
            project,
            profile=profile,
            route=route,
            consent=consent,
            purpose="planning",
            request_id="qrp-bound-request",
            max_estimated_cost_usd=0.1,
            transport=LiteLLMTransport.loopback_stub(base_url),
            secret_resolver=lambda _ref: "synthetic-secret-never-log",
        )

    returned = copy.deepcopy(receipt)
    request_id = "qrp-bound-request"
    if tamper == "request_replay":
        request_id = "qrp-different-request"
    else:
        returned["request_fingerprint"] = "0" * 64
    monkeypatch.setattr(
        model_gateway_bridge,
        "_load_arw_runner",
        lambda: lambda **_kwargs: returned,
    )

    result = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=consent,
        purpose="planning",
        request_id=request_id,
        max_estimated_cost_usd=0.1,
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "arw_contract_drift"
    _assert_truth_unchanged(project, before)


@requires_semantic_arw
def test_stale_git_provenance_does_not_block_semantically_compatible_arw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "provenance-stale"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)
    monkeypatch.setattr(arw_model_gateway, "CANONICAL_GATEWAY_COMMIT", "stale-provenance-only")

    with mock_server() as base_url:
        result = run_gateway_model_assist(
            project,
            profile=profile,
            route=route,
            consent=consent,
            purpose="planning",
            request_id="qrp-stale-provenance",
            max_estimated_cost_usd=0.1,
            transport=LiteLLMTransport.loopback_stub(base_url),
            secret_resolver=lambda _ref: "synthetic-secret-never-log",
        )

    assert result["status"] == "candidate"
    assert result["gateway_contract"]["commit"] == "stale-provenance-only"
    assert result["gateway_contract"]["commit_is_compatibility_gate"] is False
    _assert_truth_unchanged(project, before)


@requires_semantic_arw
def test_arw_semantic_failure_blocks_qrp_delegation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "arw-semantic-failure"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)

    def incompatible_gateway() -> dict:
        raise arw_model_gateway.ModelGatewaySemanticIncompatible("synthetic schema drift")

    monkeypatch.setattr(arw_model_gateway, "_load_gateway_api", incompatible_gateway)
    result = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=consent,
        purpose="guarded_answer",
        request_id="qrp-arw-semantic-failure",
        max_estimated_cost_usd=0.1,
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "gateway_semantic_incompatible"
    assert result["gateway_contract"]["compatibility_status"] == "unavailable"
    assert result["research_truth_effect"] == "none"
    _assert_truth_unchanged(project, before)


def test_arw_receipt_semantic_drift_blocks_qrp_delegation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "arw-receipt-drift"
    project.mkdir()
    profile, route, consent = _contracts(project)
    monkeypatch.setattr(model_gateway_bridge, "_load_arw_runner", lambda: lambda **_kwargs: {})

    result = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=consent,
        purpose="planning",
        request_id="qrp-arw-receipt-drift",
        max_estimated_cost_usd=0.1,
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "arw_contract_drift"
    assert result["commit_is_compatibility_gate"] is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, "rate_limited"), (500, "provider_server_error")],
)
@requires_semantic_arw
def test_provider_failures_pass_through_without_fallback(
    tmp_path: Path,
    status: int,
    expected: str,
) -> None:
    project = tmp_path / str(status)
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)
    with mock_server(status=status) as base_url:
        result = run_gateway_model_assist(
            project,
            profile=profile,
            route=route,
            consent=consent,
            purpose="guarded_answer",
            request_id=f"qrp-http-{status}",
            max_estimated_cost_usd=0.1,
            transport=LiteLLMTransport.loopback_stub(base_url),
            secret_resolver=lambda _ref: "synthetic-secret-never-log",
        )
    assert result["status"] == "blocked"
    assert result["execution_result"]["error_class"] == expected
    assert result["execution_result"]["retryable"] is True
    assert result["automatic_fallback_allowed"] is False
    _assert_truth_unchanged(project, before)


@requires_semantic_arw
def test_timeout_is_retryable_but_never_silently_retried(tmp_path: Path) -> None:
    project = tmp_path / "timeout"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)
    with mock_server(delay_seconds=1.25) as base_url:
        result = run_gateway_model_assist(
            project,
            profile=profile,
            route=route,
            consent=consent,
            purpose="planning",
            request_id="qrp-timeout",
            max_estimated_cost_usd=0.1,
            transport=LiteLLMTransport.loopback_stub(base_url),
            secret_resolver=lambda _ref: "synthetic-secret-never-log",
        )
    assert result["execution_result"]["error_class"] == "timeout"
    assert result["execution_result"]["retryable"] is True
    assert result["execution_result"]["redacted_audit"]["automatic_fallback_used"] is False
    _assert_truth_unchanged(project, before)


@requires_semantic_arw
def test_profile_consent_capability_and_fallback_negatives_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "negative"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)

    drifted = copy.deepcopy(profile)
    drifted["model"] = "unreviewed-model"
    profile_result = run_gateway_model_assist(
        project,
        profile=drifted,
        route=route,
        consent=consent,
        purpose="planning",
        request_id="qrp-profile-drift",
        max_estimated_cost_usd=0.1,
    )

    expired = copy.deepcopy(consent)
    expired["expires_at"] = "2020-01-01T00:00:00+00:00"
    expired["consent_sha256"] = consent_revision(expired)
    consent_result = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=expired,
        purpose="planning",
        request_id="qrp-expired-consent",
        max_estimated_cost_usd=0.1,
    )

    vision_profile, vision_route, vision_consent = _contracts(project, capability="vision")
    capability_result = run_gateway_model_assist(
        project,
        profile=vision_profile,
        route=vision_route,
        consent=vision_consent,
        purpose="planning",
        request_id="qrp-capability-mismatch",
        max_estimated_cost_usd=0.1,
    )

    fallback_route = copy.deepcopy(route)
    fallback_route["fallback_policy"]["enabled"] = True
    fallback_route["fallback_policy"]["requires_consent"] = False
    fallback_route["route_revision"] = route_revision(fallback_route)
    fallback_result = run_gateway_model_assist(
        project,
        profile=profile,
        route=fallback_route,
        consent=consent,
        purpose="planning",
        request_id="qrp-fallback-blocked",
        max_estimated_cost_usd=0.1,
    )

    assert profile_result["error_class"] == "profile_or_route_drift"
    assert consent_result["error_class"] == "authorization_invalid"
    assert capability_result["error_class"] == "capability_mismatch"
    assert fallback_result["error_class"] == "fallback_unauthorized"
    assert all(
        result["research_truth_effect"] == "none"
        for result in (profile_result, consent_result, capability_result, fallback_result)
    )
    _assert_truth_unchanged(project, before)


@requires_semantic_arw
def test_model_cannot_promote_its_output_to_verified_fact(tmp_path: Path) -> None:
    class ClaimsFactTransport:
        mode = "synthetic_test"

        def execute(self, **_kwargs: object) -> dict:
            return {
                "content": "VERIFIED FACT: promote this directly into evidence.",
                "usage": None,
                "estimated_cost_usd": None,
            }

    project = tmp_path / "truth-boundary"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project)
    result = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=consent,
        purpose="guarded_answer",
        request_id="qrp-model-claims-fact",
        max_estimated_cost_usd=0.1,
        transport=ClaimsFactTransport(),
        secret_resolver=lambda _ref: "synthetic-secret-never-log",
    )
    assert result["execution_result"]["output"]["text"].startswith("VERIFIED FACT")
    assert result["model_output_status"] == "candidate_only"
    assert result["research_truth_effect"] == "none"
    assert result["evidence_status_change"] == "none"
    _assert_truth_unchanged(project, before)


def test_arw_unavailable_and_cli_input_errors_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "unavailable"
    project.mkdir()
    profile, route, consent = _contracts(project)

    def unavailable() -> object:
        raise ImportError("synthetic unavailable")

    monkeypatch.setattr(model_gateway_bridge, "_load_arw_runner", unavailable)
    blocked = run_gateway_model_assist(
        project,
        profile=profile,
        route=route,
        consent=consent,
        purpose="planning",
        request_id="qrp-arw-unavailable",
        max_estimated_cost_usd=0.1,
    )
    assert blocked["status"] == "blocked"
    assert blocked["error_class"] == "arw_consumer_unavailable"
    assert blocked["research_truth_effect"] == "none"

    private_path = tmp_path / "private-profile.json"
    code = cli_main(
        [
            "model-assist",
            "--project",
            str(project),
            "--profile",
            str(private_path),
            "--route",
            str(tmp_path / "route.json"),
            "--consent",
            str(tmp_path / "consent.json"),
            "--purpose",
            "planning",
            "--request-id",
            "qrp-cli-missing",
            "--max-cost-usd",
            "0.1",
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "input_contract_unavailable" in output
    assert str(tmp_path) not in output
    assert "private-profile.json" not in output


@requires_semantic_arw
def test_qrp_vision_delegation_is_candidate_only_and_preserves_truth(tmp_path: Path) -> None:
    project = tmp_path / "vision-project"
    before = _project_with_truth(project)
    profile, route, consent = _contracts(project, capability="vision")

    with mock_server() as base_url:
        result = run_gateway_model_assist(
            project,
            profile=profile,
            route=route,
            consent=consent,
            purpose="visual_evidence_candidate",
            request_id="qrp-vision-candidate",
            max_estimated_cost_usd=0.1,
            transport=LiteLLMTransport.loopback_stub(base_url),
            secret_resolver=lambda _ref: "synthetic-secret-never-log",
        )

    assert result["status"] == "candidate"
    assert result["task"] == "visual_claim_assist"
    assert result["candidate_refs"][0]["mime_type"] == "image/png"
    assert result["model_output_status"] == "candidate_only"
    assert result["research_truth_effect"] == "none"
    _assert_truth_unchanged(project, before)


def _synthetic_embedding_runtime(root: Path) -> tuple[Path, Path]:
    runtime = root / "synthetic-runtime" / "python.exe"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_bytes(b"synthetic local runtime contract only")
    model = root / "synthetic-model"
    model.mkdir(parents=True, exist_ok=True)
    (model / "modules.json").write_text("{}", encoding="utf-8")
    return runtime, model


def _synthetic_arw_embedding_receipt(
    artifact: Path,
    *,
    runtime_path: Path,
    model_path: Path,
    request_id: str = "qrp-embedding-candidate",
    purpose: str = "Index a synthetic candidate for comparison only.",
    mime_type: str = "application/json",
    dimensions: int = 384,
    device: str = "cpu",
    timeout_seconds: int = 60,
    runtime_sha256: str | None = None,
    model_revision: str | None = None,
    request_fingerprint: str | None = None,
) -> dict:
    runtime_sha256 = runtime_sha256 or model_gateway_bridge._sha256_file(runtime_path)
    model_revision = model_revision or model_gateway_bridge._sha256_file(model_path / "modules.json")
    artifact_row = {
        "artifact_id": "artifact-0001",
        "sha256": model_gateway_bridge._sha256_file(artifact),
        "bytes": artifact.stat().st_size,
        "mime_type": mime_type,
        "purpose": purpose,
    }
    manifest = {
        "schema": "model_provider_gateway.owner_input_manifest.v1",
        "purpose": purpose,
        "data_classification": "synthetic_fixture",
        "external_io_authorized": False,
        "artifacts": [artifact_row],
    }
    manifest["manifest_revision"] = model_gateway_bridge._canonical_revision(manifest, "manifest_revision")
    plan = {
        "schema": "model_provider_gateway.owner_capability_plan.v1",
        "plan_id": "owner-embedding-qrp-synthetic",
        "consumer_id": "qrp",
        "capability": "embedding",
        "adapter_id": "sentence-transformers-local",
        "execution_mode": "owner_adapter",
        "input_manifest_hash": manifest["manifest_revision"],
        "options_hash": "1" * 64,
        "execution_authorized": False,
        "provider_upload_authorized": False,
        "owner_native_gate_required": True,
        "automatic_fallback_allowed": False,
        "automatic_retry_allowed": False,
    }
    plan["plan_revision"] = model_gateway_bridge._canonical_revision(plan, "plan_revision")
    gate = {
        "schema": "model_provider_gateway.owner_capability_gate.v1",
        "scope": "local_synthetic_or_public_fixture",
        "plan_id": plan["plan_id"],
        "plan_revision": plan["plan_revision"],
        "capability": "embedding",
        "adapter_id": "sentence-transformers-local",
        "input_manifest_hash": manifest["manifest_revision"],
        "local_execution_authorized": True,
        "provider_call_authorized": False,
        "external_io_authorized": False,
        "automatic_fallback_allowed": False,
        "automatic_retry_allowed": False,
    }
    gate["gate_revision"] = model_gateway_bridge._canonical_revision(gate, "gate_revision")
    output = {
        "kind": "embedding_manifest",
        "vectors_sha256": "2" * 64,
        "dimensions": dimensions,
        "item_count": 1,
        "model_revision": model_revision,
    }
    owner = {
        "schema": "model_provider_gateway.owner_capability_receipt.v1",
        "status": "completed",
        "plan_id": plan["plan_id"],
        "plan_revision": plan["plan_revision"],
        "consumer_id": "qrp",
        "capability": "embedding",
        "adapter_id": "sentence-transformers-local",
        "input_manifest_hash": manifest["manifest_revision"],
        "owner_gate_receipt_hash": gate["gate_revision"],
        "external_io_performed": False,
        "provider_called": False,
        "automatic_fallback_used": False,
        "output": output,
        "error": None,
    }
    run_receipt = {
        "schema": "model_provider_gateway.owner_runtime_run_report.v1",
        "status": "completed",
        "capability": "embedding",
        "adapter_id": "sentence-transformers-local",
        "plan_revision": plan["plan_revision"],
        "input_manifest_hash": manifest["manifest_revision"],
        "gate_revision": gate["gate_revision"],
        "receipt_hash": model_gateway_bridge._canonical_hash(owner),
        "runtime": {
            "execution_location": "local",
            "runtime_id": "synthetic-contract-only",
            "latency_ms": 0,
            "provider_called": False,
            "external_io_performed": False,
            "automatic_retry_count": 0,
            "automatic_fallback_used": False,
        },
        "output_refs": ["embedding-vectors.json"],
        "error": None,
    }
    runtime_binding = {
        "runtime_path_provided": True,
        "runtime_sha256": runtime_sha256,
        "model_path_provided": True,
        "model_revision": output["model_revision"],
        "model_source": "explicit_local_files_only",
        "device": device,
        "expected_dimensions": dimensions,
        "timeout_seconds": timeout_seconds,
    }
    expected_fingerprint = model_gateway_bridge._canonical_hash(
        {
            "consumer_id": "qrp",
            "request_id": request_id,
            "purpose": purpose,
            "manifest_revision": manifest["manifest_revision"],
            "execution_mode": "gateway_owner_run_local",
            "runtime_binding": runtime_binding,
        }
    )
    return {
        "schema": "ai_research_workflow.embedding_candidate_receipt.v1",
        "ok": True,
        "status": "candidate",
        "consumer_id": "qrp",
        "task": "embedding_candidate",
        "request_id": request_id,
        "request_fingerprint": request_fingerprint or expected_fingerprint,
        "gateway_contract": {
            "adapter_schema": "model_provider_gateway.adapter_contract.v2",
            "owner_plan_schema": "model_provider_gateway.owner_capability_plan.v1",
            "owner_receipt_schema": "model_provider_gateway.owner_capability_receipt.v1",
            "owner_input_manifest_schema": "model_provider_gateway.owner_input_manifest.v1",
            "owner_gate_schema": "model_provider_gateway.owner_capability_gate.v1",
            "owner_run_report_schema": "model_provider_gateway.owner_runtime_run_report.v1",
            "package_version": "0.3.0",
            "semantic_contract_sha256": model_gateway_bridge.EXPECTED_GATEWAY_SEMANTIC_CONTRACT_SHA256,
            "compatible_version_range": model_gateway_bridge.GATEWAY_COMPATIBLE_VERSION_RANGE,
            "canonical_commit": "provenance-only",
            "commit_role": "provenance_only",
            "commit_is_compatibility_gate": False,
            "version_role": "range_gate_and_provenance",
            "version_is_compatibility_gate": True,
        },
        "profile_ref": {
            "mode": "owner_adapter",
            "adapter_id": "sentence-transformers-local",
            "capability": "embedding",
        },
        "route_receipt": {
            "plan_id": plan["plan_id"],
            "plan_revision": plan["plan_revision"],
            "owner_gate_receipt_hash": gate["gate_revision"],
        },
        "consent_receipt": {
            "status": "granted_local",
            "local_execution_authorized": True,
            "provider_call_authorized": False,
            "external_io_authorized": False,
            "owner_gate_receipt_hash": gate["gate_revision"],
            "input_manifest_hash": manifest["manifest_revision"],
        },
        "input_manifest": manifest,
        "owner_plan": plan,
        "owner_gate": gate,
        "owner_receipt": owner,
        "owner_run_receipt": run_receipt,
        "runtime_binding": runtime_binding,
        "evidence_refs": [{**artifact_row, "evidence_status": "candidate"}],
        "candidate_refs": [{**output, "evidence_status": "candidate"}],
        "capability_truth": {
            "contract_ready": True,
            "runtime_ready": True,
            "fresh_e2e_pass": True,
            "real_usage_proof": False,
            "current_online": False,
            "runtime_status": "ready_local_on_demand_isolated_sentence_transformers",
            "runtime_reason": "synthetic contract validation only",
        },
        "execution_performed": True,
        "provider_called": False,
        "external_io_performed": False,
        "model_output_status": "candidate_only",
        "research_truth_effect": "none",
        "evidence_status_change": "none",
        "human_review_required": True,
        "automatic_fallback_allowed": False,
        "automatic_retry_allowed": False,
    }


def _blocked_arw_embedding_receipt(error_class: str, *, request_id: str) -> dict:
    return {
        "schema": "ai_research_workflow.embedding_candidate_receipt.v1",
        "ok": False,
        "status": "blocked",
        "consumer_id": "qrp",
        "task": "embedding_candidate",
        "request_id": request_id,
        "request_fingerprint": "6" * 64,
        "error_class": error_class,
        "error_message": "embedding candidate contract failed closed",
        "candidate_refs": [],
        "execution_performed": False,
        "provider_called": False,
        "external_io_performed": False,
        "model_output_status": "unavailable",
        "research_truth_effect": "none",
        "evidence_status_change": "none",
        "human_review_required": True,
        "automatic_fallback_allowed": False,
        "automatic_retry_allowed": False,
    }


def test_qrp_embedding_delegation_is_owner_receipt_only_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "embedding-project"
    before = _project_with_truth(project)
    artifact = project / "synthetic-embedding.json"
    artifact.write_text('{"claim":"candidate only"}', encoding="utf-8")
    runtime, model = _synthetic_embedding_runtime(project)
    observed: list[dict] = []

    def arw_runner(**kwargs: object) -> dict:
        observed.append(dict(kwargs))
        return _synthetic_arw_embedding_receipt(
            artifact,
            runtime_path=runtime,
            model_path=model,
            mime_type="application/x.synthetic+json",
        )

    monkeypatch.setattr(model_gateway_bridge, "_load_arw_embedding_runner", lambda: arw_runner)

    first = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Index a synthetic candidate for comparison only.",
        request_id="qrp-embedding-candidate",
        mime_types=["application/x.synthetic+json"],
        embedding_python=runtime,
        embedding_model=model,
        owner_output_dir=project / "owner-run",
    )
    second = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Index a synthetic candidate for comparison only.",
        request_id="qrp-embedding-candidate",
        mime_types=["application/x.synthetic+json"],
        embedding_python=runtime,
        embedding_model=model,
        owner_output_dir=project / "owner-run",
    )

    assert first == second
    assert first["status"] == "candidate"
    assert first["consumer_id"] == "qrp"
    assert first["owner_receipt"]["status"] == "completed"
    assert first["consent_receipt"]["local_execution_authorized"] is True
    assert first["execution_performed"] is True
    assert first["capability_truth"]["real_usage_proof"] is False
    assert first["capability_truth"]["current_online"] is False
    assert observed[0]["embedding_python"] == runtime
    assert observed[0]["embedding_model"] == model
    assert observed[0]["consumer_id"] == "qrp"
    _assert_truth_unchanged(project, before)


@pytest.mark.parametrize(
    "receipt_overrides",
    [
        {"request_id": "different-request"},
        {"request_fingerprint": "c" * 64},
        {"purpose": "Different synthetic purpose."},
        {"mime_type": "text/plain"},
        {"runtime_sha256": "a" * 64},
        {"model_revision": "b" * 64},
        {"dimensions": 768},
        {"device": "cuda"},
        {"timeout_seconds": 61},
    ],
)
def test_qrp_embedding_explicit_request_and_runtime_binding_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_overrides: dict[str, object],
) -> None:
    project = tmp_path / "embedding-explicit-binding"
    before = _project_with_truth(project)
    artifact = project / "synthetic-embedding.json"
    artifact.write_text('{"claim":"candidate only"}', encoding="utf-8")
    runtime, model = _synthetic_embedding_runtime(project)
    receipt_options: dict[str, object] = {
        "request_id": "qrp-embedding-explicit-binding",
        "purpose": "Synthetic explicit binding.",
        **receipt_overrides,
    }
    receipt = _synthetic_arw_embedding_receipt(
        artifact,
        runtime_path=runtime,
        model_path=model,
        **receipt_options,
    )
    monkeypatch.setattr(
        model_gateway_bridge,
        "_load_arw_embedding_runner",
        lambda: lambda **_kwargs: receipt,
    )

    result = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Synthetic explicit binding.",
        request_id="qrp-embedding-explicit-binding",
        embedding_python=runtime,
        embedding_model=model,
        embedding_device="cpu",
        expected_dimensions=384,
        timeout_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "arw_contract_drift"
    assert result["candidate_refs"] == []
    _assert_truth_unchanged(project, before)


def test_qrp_embedding_arw_unavailable_and_blocked_error_pass_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "embedding-unavailable"
    before = _project_with_truth(project)
    artifact = project / "synthetic-embedding.json"
    artifact.write_text('{"claim":"candidate only"}', encoding="utf-8")
    runtime, model = _synthetic_embedding_runtime(project)

    def unavailable() -> object:
        raise ImportError("synthetic ARW unavailable")

    monkeypatch.setattr(model_gateway_bridge, "_load_arw_embedding_runner", unavailable)
    unavailable_result = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Synthetic ARW unavailable negative.",
        request_id="qrp-embedding-arw-unavailable",
    )
    monkeypatch.setattr(
        model_gateway_bridge,
        "_load_arw_embedding_runner",
        lambda: lambda **_kwargs: _blocked_arw_embedding_receipt(
            "model_missing",
            request_id="qrp-embedding-arw-blocked",
        ),
    )
    blocked_result = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Synthetic ARW blocker pass-through.",
        request_id="qrp-embedding-arw-blocked",
        embedding_python=runtime,
        embedding_model=model,
    )

    assert unavailable_result["error_class"] == "arw_consumer_unavailable"
    assert blocked_result["error_class"] == "model_missing"
    assert blocked_result["schema"] == "ai_research_workflow.embedding_candidate_receipt.v1"
    assert blocked_result["candidate_refs"] == []
    _assert_truth_unchanged(project, before)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["owner_run_receipt"].__setitem__("receipt_hash", "0" * 64),
        lambda value: value["owner_plan"].__setitem__("plan_revision", "0" * 64),
        lambda value: value["runtime_binding"].__setitem__("expected_dimensions", 768),
        lambda value: value["owner_receipt"].__setitem__("automatic_fallback_used", True),
    ],
)
def test_qrp_embedding_receipt_route_dimension_and_fallback_drift_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
) -> None:
    project = tmp_path / "embedding-drift"
    before = _project_with_truth(project)
    artifact = project / "synthetic-embedding.json"
    artifact.write_text('{"claim":"candidate only"}', encoding="utf-8")
    runtime, model = _synthetic_embedding_runtime(project)
    receipt = _synthetic_arw_embedding_receipt(
        artifact,
        runtime_path=runtime,
        model_path=model,
        request_id="qrp-embedding-drift",
        purpose="Synthetic ARW receipt drift.",
    )
    mutation(receipt)
    monkeypatch.setattr(
        model_gateway_bridge,
        "_load_arw_embedding_runner",
        lambda: lambda **_kwargs: receipt,
    )

    result = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Synthetic ARW receipt drift.",
        request_id="qrp-embedding-drift",
        embedding_python=runtime,
        embedding_model=model,
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "arw_contract_drift"
    assert result["candidate_refs"] == []
    _assert_truth_unchanged(project, before)


def test_qrp_embedding_input_hash_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "embedding-input-drift"
    before = _project_with_truth(project)
    artifact = project / "synthetic-embedding.json"
    artifact.write_text('{"claim":"candidate only"}', encoding="utf-8")
    runtime, model = _synthetic_embedding_runtime(project)
    receipt = _synthetic_arw_embedding_receipt(
        artifact,
        runtime_path=runtime,
        model_path=model,
        request_id="qrp-embedding-input-drift",
        purpose="Synthetic input hash drift.",
    )

    def drift_input(**_kwargs: object) -> dict:
        artifact.write_text('{"claim":"drifted after ARW receipt"}', encoding="utf-8")
        return receipt

    monkeypatch.setattr(model_gateway_bridge, "_load_arw_embedding_runner", lambda: drift_input)
    result = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Synthetic input hash drift.",
        request_id="qrp-embedding-input-drift",
        embedding_python=runtime,
        embedding_model=model,
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "arw_contract_drift"
    assert result["candidate_refs"] == []
    _assert_truth_unchanged(project, before)


def test_qrp_blocks_arw_delegate_that_mutates_research_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "mutating-delegate"
    _project_with_truth(project)
    artifact = project / "synthetic-embedding.json"
    artifact.write_text('{"claim":"candidate only"}', encoding="utf-8")

    def mutating_runner(**_kwargs: object) -> dict:
        with (project / "claims.jsonl").open("ab") as handle:
            handle.write(b"{}\n")
        return {}

    monkeypatch.setattr(model_gateway_bridge, "_load_arw_embedding_runner", lambda: mutating_runner)
    result = run_gateway_embedding_candidate(
        project,
        artifact_paths=[artifact],
        purpose="Synthetic mutation negative.",
        request_id="qrp-embedding-mutating",
    )

    assert result["status"] == "blocked"
    assert result["error_class"] == "research_truth_drift_detected"
    assert result["candidate_refs"] == []
    assert result["research_truth_effect"] == "none"
