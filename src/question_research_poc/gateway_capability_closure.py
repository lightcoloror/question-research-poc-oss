"""Recoverable synthetic QRP/ARW capability closure using closure-run.v1."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .guarded_e2e_fixture import run_guarded_e2e_fixture
from .model_gateway_bridge import (
    _truth_snapshot,
    run_gateway_embedding_candidate,
    run_gateway_model_assist,
)
from .research_output import export_research_output

CLOSURE_SCHEMA_VERSION = "closure-run.v1"
CAPABILITY_MATRIX_SCHEMA = "question_research_poc.gateway_capability_matrix.v1"
COMPLETION_RECEIPT_SCHEMA = "question_research_poc.gateway_capability_closure_receipt.v1"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")


def run_gateway_capability_closure(
    *,
    output_root: str | Path,
    closure_run_id: str,
    closure_schema_path: str | Path,
    source_inventory_path: str | Path,
    owner_routing_path: str | Path,
    tool_registry_path: str | Path,
    resume: bool = False,
) -> dict[str, Any]:
    """Run or resume one fully synthetic, local-only research capability closure."""
    if not _RUN_ID.fullmatch(closure_run_id):
        raise ValueError("closure_run_id must use 3-80 safe filename characters")
    schema_path = Path(closure_schema_path).expanduser().resolve()
    authority_paths = {
        "source_inventory": Path(source_inventory_path).expanduser().resolve(),
        "owner_routing": Path(owner_routing_path).expanduser().resolve(),
        "tool_registry": Path(tool_registry_path).expanduser().resolve(),
    }
    if not schema_path.is_file():
        raise FileNotFoundError("canonical closure_run.v1 schema is unavailable")
    for name, path in authority_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"closure authority input is unavailable: {name}")

    run_dir = Path(output_root).expanduser().resolve() / closure_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    resume_entry = (
        "python -m question_research_poc.cli gateway-capability-closure "
        f"--output-root . --closure-run-id {closure_run_id} "
        "--closure-schema <closure-run.v1.schema.json> "
        "--source-inventory <SOURCE_INVENTORY.json> "
        "--owner-routing <owner-routing-status.json> "
        "--tool-registry <tool-registry.json> --resume"
    )
    fingerprints = {
        "closure_schema": _sha256_file(schema_path),
        **{name: _sha256_file(path) for name, path in authority_paths.items()},
    }
    manifest_path = run_dir / "run-manifest.json"
    manifest = {
        "schema": "question_research_poc.gateway_capability_closure_manifest.v1",
        "closure_run_id": closure_run_id,
        "input_fingerprints": fingerprints,
        "contract_versions": {
            "closure_run": CLOSURE_SCHEMA_VERSION,
            "local_tool_closure": "local-tool-closure-run.v2",
            "closure_truth": "closure-truth.v1",
            "research_output": "research-output.v1",
            "gateway_adapter": "model_provider_gateway.adapter_contract.v2",
            "gateway_owner_plan": "model_provider_gateway.owner_capability_plan.v1",
        },
        "resume_entry": resume_entry,
        "execution_authorized": False,
    }
    if manifest_path.is_file():
        existing_manifest = _read_json(manifest_path)
        if existing_manifest != manifest:
            raise ValueError("closure input or contract drift; use a new closure_run_id")
    elif resume:
        raise ValueError("closure run does not exist for resume")
    else:
        _write_json(manifest_path, manifest)

    closure_path = run_dir / "closure-run.json"
    if closure_path.is_file():
        closure = _read_json(closure_path)
        validate_closure_run(closure, run_dir=run_dir, schema_path=schema_path)
        return _completion_result(
            closure=closure,
            run_dir=run_dir,
            idempotent_reuse=True,
            resumed=resume,
        )

    project_root = run_dir / "synthetic-project"
    guarded = run_guarded_e2e_fixture(project_root, reviewer="gateway-capability-closure-fixture")
    if not guarded.get("ok"):
        raise RuntimeError("guarded synthetic research fixture did not complete")
    research_output_path = run_dir / "artifacts" / "research-output.v1.json"
    research_export = export_research_output(
        project_root,
        output_path=research_output_path,
        scope="Synthetic Gateway capability closure only.",
        audience="contract verifier",
        requested_outputs=["guarded_final_answer", "capability_receipts"],
        scope_constraints=["offline_only", "candidate_model_outputs_are_not_evidence"],
    )
    if not research_export.get("ok"):
        raise RuntimeError("research-output.v1 export failed")
    truth_before = _truth_snapshot(project_root)

    input_dir = run_dir / "synthetic-inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    text_artifact = input_dir / "research-candidate.json"
    vision_artifact = input_dir / "research-candidate.png"
    _write_bytes_once(text_artifact, b'{"claim":"synthetic candidate only"}\n')
    _write_bytes_once(
        vision_artifact,
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
            "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
        ),
    )

    text_profile, text_route, text_consent = _persisted_provider_contracts(
        run_dir,
        text_artifact,
        capability="text",
    )
    vision_profile, vision_route, vision_consent = _persisted_provider_contracts(
        run_dir,
        vision_artifact,
        capability="vision",
    )
    receipt_dir = project_root / "model-assist-receipts"
    text_receipt_path = receipt_dir / "closure-text.json"
    vision_receipt_path = receipt_dir / "closure-vision.json"

    def run_text_and_vision(transport: Any | None) -> tuple[dict[str, Any], dict[str, Any]]:
        text_receipt = run_gateway_model_assist(
            project_root,
            profile=text_profile,
            route=text_route,
            consent=text_consent,
            purpose="planning",
            request_id=f"{closure_run_id}-text",
            max_estimated_cost_usd=0.1,
            receipt_path=text_receipt_path,
            transport=transport,
            secret_resolver=lambda _ref: "synthetic-loopback-key",
        )
        vision_receipt = run_gateway_model_assist(
            project_root,
            profile=vision_profile,
            route=vision_route,
            consent=vision_consent,
            purpose="visual_evidence_candidate",
            request_id=f"{closure_run_id}-vision",
            max_estimated_cost_usd=0.1,
            receipt_path=vision_receipt_path,
            transport=transport,
            secret_resolver=lambda _ref: "synthetic-loopback-key",
        )
        return text_receipt, vision_receipt

    if text_receipt_path.is_file() and vision_receipt_path.is_file():
        text_receipt, vision_receipt = run_text_and_vision(None)
    else:
        from model_provider_gateway.execution import LiteLLMTransport
        from model_provider_gateway.mock_server import mock_server

        with mock_server() as base_url:
            text_receipt, vision_receipt = run_text_and_vision(
                LiteLLMTransport.loopback_stub(base_url)
            )
    capability_receipts = {"text": text_receipt, "vision": vision_receipt}
    if any(receipt.get("status") not in {"candidate", "blocked"} for receipt in capability_receipts.values()):
        raise RuntimeError("text or vision closure returned an unknown state")

    embedding_path = project_root / "embedding-assist-receipts" / "closure.json"
    embedding_receipt = run_gateway_embedding_candidate(
        project_root,
        artifact_paths=[text_artifact],
        purpose="Index a synthetic research candidate for comparison only.",
        request_id=f"{closure_run_id}-embedding",
        receipt_path=embedding_path,
    )
    embedding_status = embedding_receipt.get("status")
    if embedding_status not in {"candidate", "blocked"}:
        raise RuntimeError("embedding owner receipt closure returned an unknown state")

    embedding_drift_error = None
    if embedding_status == "candidate":
        from research_workflow.embedding_gateway import validate_embedding_candidate_receipt

        original_text = text_artifact.read_bytes()
        text_artifact.write_bytes(original_text + b"drift")
        try:
            validate_embedding_candidate_receipt(embedding_receipt, artifact_paths=[text_artifact])
        except ValueError as exc:
            embedding_drift_error = (
                "input_hash_mismatch" if "input_hash_mismatch" in str(exc) else type(exc).__name__
            )
        finally:
            text_artifact.write_bytes(original_text)
        if embedding_drift_error != "input_hash_mismatch":
            raise RuntimeError("synthetic hash-drift gate was not observed")

    capability_receipts["embedding"] = embedding_receipt
    blocked_capability = next(
        (name for name, receipt in capability_receipts.items() if receipt.get("status") == "blocked"),
        None,
    )
    if blocked_capability is None:
        drift_error = embedding_drift_error
        failure_point = "input_hash_gate"
    else:
        drift_error = str(capability_receipts[blocked_capability].get("error_class") or "runtime_unavailable")
        failure_point = f"{blocked_capability}_runtime_gate"

    resumed_embedding = run_gateway_embedding_candidate(
        project_root,
        artifact_paths=[text_artifact],
        purpose="Index a synthetic research candidate for comparison only.",
        request_id=f"{closure_run_id}-embedding",
        receipt_path=embedding_path,
    )
    if resumed_embedding != embedding_receipt:
        raise RuntimeError("embedding resume was not idempotent")
    if _truth_snapshot(project_root) != truth_before:
        raise RuntimeError("model capability closure changed QRP research truth")

    matrix = _capability_matrix(
        text_receipt=text_receipt,
        vision_receipt=vision_receipt,
        embedding_receipt=embedding_receipt,
    )
    matrix_path = run_dir / "capability-matrix.json"
    _write_json_once(matrix_path, matrix)
    facades = _write_facades(
        run_dir=run_dir,
        research_output_path=research_output_path,
        research_export=research_export,
        guarded=guarded,
        text_receipt=text_receipt,
        vision_receipt=vision_receipt,
        embedding_receipt=embedding_receipt,
        matrix_path=matrix_path,
        authority_paths=authority_paths,
    )
    intake_stage = _stage_receipt(
        run_dir / "stages" / "intake-receipt.json",
        name="intake",
        status="passed",
        evidence_status="fresh",
        detail={
            "guarded_fixture_status": guarded["status"],
            "research_output_sha256": research_export["artifact_sha256"],
        },
    )
    linkage_stage = _stage_receipt(
        run_dir / "stages" / "linkage-failure-receipt.json",
        name="linkage",
        status="failed",
        evidence_status="fresh",
        failure_point=failure_point,
        error_class=drift_error,
        retryable=True,
        resume_entry=resume_entry,
        detail={
            "failure_injected": blocked_capability is None,
            "embedding_status": embedding_status,
            "external_io_performed": False,
        },
    )
    review_stage = _stage_receipt(
        run_dir / "stages" / "review-resumed-receipt.json",
        name="review",
        status="resumed",
        evidence_status="fresh",
        resume_entry=resume_entry,
        detail={
            "text_status": text_receipt["status"],
            "vision_status": vision_receipt["status"],
            "embedding_status": embedding_receipt["status"],
            "research_truth_unchanged": True,
        },
    )
    final_receipt = {
        "schema_version": "codex-thread-receipt.v0.1",
        "receipt_id": hashlib.sha256(f"{closure_run_id}:final".encode()).hexdigest()[:32],
        "dispatch_id": "RESEARCH-GATEWAY-CAPABILITY-CLOSE-20260812-01",
        "status": "completed",
        "closure_run_id": closure_run_id,
        "execution_authorized": False,
        "external_api_called": False,
        "real_usage_proof": False,
        "current_online": False,
    }
    final_receipt_path = run_dir / "final-receipt.json"
    _write_json_once(final_receipt_path, final_receipt)

    closure = {
        "schema_version": CLOSURE_SCHEMA_VERSION,
        "closure_run_id": closure_run_id,
        "parent_run_id": None,
        "causation": {
            "dispatch_ref": "RESEARCH-GATEWAY-CAPABILITY-CLOSE-20260812-01",
            "cause_type": "synthetic_fixture",
        },
        "profile": "qrp-arw-gateway-synthetic-loopback",
        "contract_versions": {
            "closure_run": CLOSURE_SCHEMA_VERSION,
            "local_tool_closure": "local-tool-closure-run.v2",
            "closure_truth": "closure-truth.v1",
            "dispatch": "codex-agent-dispatch-card.v0.1",
            "receipt": "codex-thread-receipt.v0.1",
        },
        "input_refs": facades["input_refs"],
        "authority_refs": facades["authority_refs"],
        "stages": [
            _stage_ref(intake_stage, run_dir=run_dir),
            _stage_ref(linkage_stage, run_dir=run_dir),
            _stage_ref(review_stage, run_dir=run_dir),
        ],
        "truth": {
            "contract_ready": {
                "value": True,
                "state": "verified",
                "reason_codes": ["text_vision_and_embedding_fail_closed_contracts_validated"],
            },
            "runtime_ready": {
                "value": blocked_capability is None,
                "state": (
                    "ready_local_synthetic"
                    if blocked_capability is None
                    else f"blocked_{blocked_capability}_{drift_error}"
                ),
                "reason_codes": [
                    (
                        "all_synthetic_capability_runtimes_completed"
                        if blocked_capability is None
                        else f"{blocked_capability}_runtime_not_configured_or_unavailable"
                    )
                ],
            },
            "fresh_e2e_pass": {
                "value": blocked_capability is None,
                "state": (
                    "fresh_synthetic_loopback"
                    if blocked_capability is None
                    else f"partial_capability_pass_{blocked_capability}_fail_closed"
                ),
                "reason_codes": [
                    (
                        "text_vision_loopback_and_embedding_fixture_passed"
                        if blocked_capability is None
                        else f"{blocked_capability}_runtime_gate_blocked_full_e2e"
                    )
                ],
            },
            "real_usage_proof": {
                "value": False,
                "state": "synthetic_only",
                "reason_codes": ["no_business_material_or_real_provider"],
            },
            "current_online": {
                "value": False,
                "state": "not_observed",
                "reason_codes": ["no_service_or_online_provider_started"],
            },
            "verified_available_requires": [
                "contract_ready",
                "runtime_ready",
                "fresh_e2e_pass",
                "real_usage_proof",
            ],
            "verified_available": False,
        },
        "final_review_packet_ref": facades["input_refs"]["review_packet"],
        "final_receipt_ref": _input_ref(
            final_receipt_path,
            run_dir=run_dir,
            contract="codex-thread-receipt.v0.1",
            schema_version="codex-thread-receipt.v0.1",
        ),
        "execution_authorized": False,
    }
    validate_closure_run(closure, run_dir=run_dir, schema_path=schema_path)
    _write_json(closure_path, closure)
    validate_closure_run(_read_json(closure_path), run_dir=run_dir, schema_path=schema_path)
    return _completion_result(
        closure=closure,
        run_dir=run_dir,
        idempotent_reuse=False,
        resumed=resume,
    )


def validate_closure_run(
    closure: dict[str, Any],
    *,
    run_dir: str | Path,
    schema_path: str | Path,
) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    schema = _read_json(Path(schema_path))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(closure)
    expected_contracts = {
        "material_manifest": "material-manifest.v1",
        "evidence_bundle": "evidence-bundle.v1",
        "content_brief": "content-brief.v1",
        "review_packet": "review-packet.v1",
        "service_profile": "service-profile.v1",
    }
    refs: list[dict[str, Any]] = []
    for name, expected in expected_contracts.items():
        ref = closure["input_refs"][name]
        if ref["contract"] != expected:
            raise ValueError(f"input contract mismatch: {name}")
        payload = _read_ref(root, ref)
        if payload.get("facade_contract") != expected:
            raise ValueError(f"input facade mismatch: {name}")
        if payload.get("metadata", {}).get("execution_authorized") is not False:
            raise ValueError(f"input facade grants execution: {name}")
        if name == "evidence_bundle":
            _read_ref(root, payload["research_output_ref"])
        if name == "service_profile":
            _read_ref(root, payload["capability_matrix_ref"])
        refs.append(ref)
    refs.extend(closure["authority_refs"].values())
    refs.extend(stage["receipt_ref"] for stage in closure["stages"])
    refs.extend([closure["final_review_packet_ref"], closure["final_receipt_ref"]])
    for ref in refs:
        _read_ref(root, ref)
    if any(ref.get("grants_execution") is not False for ref in closure["authority_refs"].values()):
        raise ValueError("authority metadata grants execution")
    names = [stage["name"] for stage in closure["stages"]]
    if len(names) != len(set(names)):
        raise ValueError("duplicate closure stage")
    failures = [stage for stage in closure["stages"] if stage["status"] == "failed"]
    if not failures or not all(stage["retryable"] and stage["resume_entry"] for stage in failures):
        raise ValueError("failure resume contract missing")
    if not any(stage["status"] == "resumed" for stage in closure["stages"]):
        raise ValueError("resume receipt missing")
    if closure["truth"]["fresh_e2e_pass"]["value"] is True and any(
        stage["evidence_status"] != "fresh" for stage in closure["stages"]
    ):
        raise ValueError("historical stage cannot support fresh_e2e_pass")
    required = closure["truth"]["verified_available_requires"]
    expected_available = all(closure["truth"][name]["value"] is True for name in required)
    if closure["truth"]["verified_available"] != expected_available:
        raise ValueError("verified_available four-gate mismatch")
    current_online = closure["truth"]["current_online"]
    if current_online["value"] is True and current_online["state"] != "current_observation":
        raise ValueError("current_online requires a current observation")
    if closure.get("execution_authorized") is not False:
        raise ValueError("closure metadata grants execution")
    return closure


def _provider_contracts(artifact: Path, *, capability: str) -> tuple[dict, dict, dict]:
    from model_provider_gateway.consent import build_consent_plan
    from model_provider_gateway.profile import build_profile
    from model_provider_gateway.route import build_route_plan

    preset = "modelscope-glm-5-2" if capability == "text" else "siliconflow-glm-4-5v"
    profile = build_profile(
        preset,
        "env:MPG_SYNTHETIC_LOOPBACK_ONLY",
        last_verified="2026-08-05T00:00:00+00:00",
        max_calls=4,
        max_cost_usd=1.0,
        timeout_seconds=2,
    )
    route = build_route_plan(
        f"research-closure-{capability}",
        capability,
        [profile],
        max_calls=4,
        max_cost_usd=1.0,
    )
    consent = build_consent_plan(
        route,
        [artifact],
        capability=capability,
        purpose="Produce a synthetic candidate for human review only.",
        data_type="synthetic_research_fixture",
        max_calls=4,
        max_cost_usd=1.0,
    )
    return profile, route, consent


def _persisted_provider_contracts(
    run_dir: Path,
    artifact: Path,
    *,
    capability: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path = run_dir / "contracts" / f"{capability}-provider-contract.json"
    if path.is_file():
        payload = _read_json(path)
    else:
        profile, route, consent = _provider_contracts(artifact, capability=capability)
        payload = {
            "schema": "question_research_poc.persisted_provider_contract.v1",
            "capability": capability,
            "profile": profile,
            "route": route,
            "consent": consent,
            "execution_authorized": False,
        }
        _write_json_once(path, payload)
    if payload.get("capability") != capability or payload.get("execution_authorized") is not False:
        raise ValueError(f"persisted provider contract drift: {capability}")
    values = tuple(payload.get(name) for name in ("profile", "route", "consent"))
    if not all(isinstance(value, dict) for value in values):
        raise ValueError(f"persisted provider contract is incomplete: {capability}")
    return values  # type: ignore[return-value]


def _capability_matrix(
    *,
    text_receipt: dict[str, Any],
    vision_receipt: dict[str, Any],
    embedding_receipt: dict[str, Any],
) -> dict[str, Any]:
    def model_row(receipt: dict[str, Any]) -> dict[str, Any]:
        status = receipt.get("status")
        if status == "candidate":
            return {
                "contract_ready": True,
                "runtime_ready": True,
                "fresh_e2e_pass": True,
                "real_usage_proof": False,
                "current_online": False,
                "execution_mode": "litellm_loopback_stub",
                "runtime_status": "ready_local_synthetic_loopback",
                "candidate_only": True,
            }
        if status == "blocked":
            return {
                "contract_ready": True,
                "runtime_ready": False,
                "fresh_e2e_pass": False,
                "real_usage_proof": False,
                "current_online": False,
                "execution_mode": "delegated_fail_closed_probe",
                "runtime_status": f"blocked_{receipt.get('error_class', 'runtime_unavailable')}",
                "candidate_only": False,
            }
        raise ValueError("model-assist receipt status is not representable")

    embedding_status = embedding_receipt.get("status")
    if embedding_status == "candidate":
        embedding_truth = embedding_receipt["capability_truth"]
        embedding_row = {
            "contract_ready": embedding_truth["contract_ready"],
            "runtime_ready": embedding_truth["runtime_ready"],
            "fresh_e2e_pass": embedding_truth["fresh_e2e_pass"],
            "fresh_fail_closed_probe_pass": True,
            "real_usage_proof": embedding_truth["real_usage_proof"],
            "current_online": embedding_truth["current_online"],
            "execution_mode": "owner_receipt_validated_fixture",
            "runtime_status": embedding_truth["runtime_status"],
            "candidate_only": True,
        }
    elif embedding_status == "blocked":
        embedding_row = {
            "contract_ready": True,
            "runtime_ready": False,
            "fresh_e2e_pass": False,
            "fresh_fail_closed_probe_pass": True,
            "real_usage_proof": False,
            "current_online": False,
            "execution_mode": "owner_receipt_fail_closed_probe",
            "runtime_status": f"blocked_{embedding_receipt['error_class']}",
            "candidate_only": False,
        }
    else:
        raise ValueError("embedding receipt status is not representable")
    rows = {
        "text": model_row(text_receipt),
        "vision": model_row(vision_receipt),
        "embedding": embedding_row,
    }
    return {
        "schema": CAPABILITY_MATRIX_SCHEMA,
        "consumers": ["qrp", "arw"],
        "capabilities": rows,
        "invariants": {
            "provider_catalog_copied": False,
            "embedding_store_created": False,
            "silent_fallback_allowed": False,
            "research_truth_changed": False,
            "real_provider_called": False,
            "external_api_called": False,
            "service_9082": "stopped_by_design",
        },
    }


def _write_facades(
    *,
    run_dir: Path,
    research_output_path: Path,
    research_export: dict[str, Any],
    guarded: dict[str, Any],
    text_receipt: dict[str, Any],
    vision_receipt: dict[str, Any],
    embedding_receipt: dict[str, Any],
    matrix_path: Path,
    authority_paths: dict[str, Path],
) -> dict[str, Any]:
    inputs = run_dir / "inputs"
    authority = run_dir / "authority"
    payloads = {
        "material_manifest": {
            "facade_contract": "material-manifest.v1",
            "schema_version": "gateway-artifact-bindings.v1",
            "metadata": {"execution_authorized": False},
            "artifacts": {
                "text": text_receipt.get("candidate_refs", []),
                "vision": vision_receipt.get("candidate_refs", []),
                "embedding": embedding_receipt.get("evidence_refs", []),
            },
        },
        "evidence_bundle": {
            "facade_contract": "evidence-bundle.v1",
            "schema_version": "research-output.v1",
            "metadata": {"execution_authorized": False},
            "research_output_ref": {
                "path": research_output_path.relative_to(run_dir).as_posix(),
                "sha256": research_export["artifact_sha256"],
            },
        },
        "content_brief": {
            "facade_contract": "content-brief.v1",
            "schema_version": "not-applicable-research-closure.v1",
            "metadata": {"execution_authorized": False},
            "status": "not_applicable",
        },
        "review_packet": {
            "facade_contract": "review-packet.v1",
            "schema_version": "qrp-guarded-review.v1",
            "metadata": {"execution_authorized": False},
            "guarded_fixture_status": guarded["status"],
            "model_outputs": "candidate_only_human_review_required",
        },
        "service_profile": {
            "facade_contract": "service-profile.v1",
            "schema_version": CAPABILITY_MATRIX_SCHEMA,
            "metadata": {"execution_authorized": False},
            "capability_matrix_ref": {
                "path": matrix_path.relative_to(run_dir).as_posix(),
                "sha256": _sha256_file(matrix_path),
            },
        },
    }
    input_refs = {}
    names = {
        "material_manifest": "material-manifest.json",
        "evidence_bundle": "evidence-bundle.json",
        "content_brief": "content-brief.json",
        "review_packet": "review-packet.json",
        "service_profile": "service-profile.json",
    }
    for name, payload in payloads.items():
        path = inputs / names[name]
        _write_json_once(path, payload)
        input_refs[name] = _input_ref(
            path,
            run_dir=run_dir,
            contract=payload["facade_contract"],
            schema_version=payload["schema_version"],
        )

    authority_refs = {}
    authority_contracts = {
        "source_inventory": "source-inventory.snapshot.v1",
        "owner_routing": "owner-routing.snapshot.v1",
        "tool_registry": "tool-registry.snapshot.v1",
    }
    for name, source_path in authority_paths.items():
        payload = {
            "facade_contract": authority_contracts[name],
            "schema_version": authority_contracts[name],
            "metadata": {"execution_authorized": False},
            "source_sha256": _sha256_file(source_path),
            "source_name": source_path.name,
        }
        target = authority / f"{name.replace('_', '-')}.json"
        _write_json_once(target, payload)
        ref = _input_ref(
            target,
            run_dir=run_dir,
            contract=authority_contracts[name],
            schema_version=authority_contracts[name],
        )
        ref.update({"metadata_only": True, "grants_execution": False})
        authority_refs[name] = ref
    return {"input_refs": input_refs, "authority_refs": authority_refs}


def _stage_receipt(
    path: Path,
    *,
    name: str,
    status: str,
    evidence_status: str,
    detail: dict[str, Any],
    failure_point: str | None = None,
    error_class: str | None = None,
    retryable: bool = False,
    resume_entry: str | None = None,
) -> dict[str, Any]:
    if path.is_file():
        return _read_json(path)
    value = {
        "schema_version": "closure-stage-receipt.v1",
        "name": name,
        "status": status,
        "evidence_status": evidence_status,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "failure_point": failure_point,
        "error_class": error_class,
        "retryable": retryable,
        "resume_entry": resume_entry,
        "detail": detail,
        "execution_authorized": False,
    }
    _write_json(path, value)
    return value


def _stage_ref(receipt: dict[str, Any], *, run_dir: Path) -> dict[str, Any]:
    path = run_dir / "stages" / {
        "intake": "intake-receipt.json",
        "linkage": "linkage-failure-receipt.json",
        "review": "review-resumed-receipt.json",
    }[receipt["name"]]
    return {
        "name": receipt["name"],
        "status": receipt["status"],
        "receipt_ref": _input_ref(
            path,
            run_dir=run_dir,
            contract="closure-stage-receipt.v1",
            schema_version="closure-stage-receipt.v1",
        ),
        "evidence_status": receipt["evidence_status"],
        "checked_at": receipt["checked_at"],
        "failure_point": receipt["failure_point"],
        "error_class": receipt["error_class"],
        "retryable": receipt["retryable"],
        "resume_entry": receipt["resume_entry"],
    }


def _input_ref(
    path: Path,
    *,
    run_dir: Path,
    contract: str,
    schema_version: str,
) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(run_dir.resolve()).as_posix(),
        "sha256": _sha256_file(path),
        "contract": contract,
        "schema_version": schema_version,
    }


def _read_ref(root: Path, ref: dict[str, Any]) -> dict[str, Any]:
    path = (root / ref["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("closure reference escapes run directory") from exc
    if not path.is_file():
        raise ValueError(f"closure reference missing: {ref['path']}")
    if _sha256_file(path) != ref["sha256"]:
        raise ValueError(f"closure reference hash drift: {ref['path']}")
    return _read_json(path)


def _completion_result(
    *,
    closure: dict[str, Any],
    run_dir: Path,
    idempotent_reuse: bool,
    resumed: bool,
) -> dict[str, Any]:
    return {
        "schema": COMPLETION_RECEIPT_SCHEMA,
        "ok": True,
        "status": "completed",
        "closure_run_id": closure["closure_run_id"],
        "closure_run_path": str(run_dir / "closure-run.json"),
        "capability_matrix_path": str(run_dir / "capability-matrix.json"),
        "resume_entry": next(
            stage["resume_entry"]
            for stage in closure["stages"]
            if stage["status"] == "failed"
        ),
        "failure_point": next(
            stage["failure_point"]
            for stage in closure["stages"]
            if stage["status"] == "failed"
        ),
        "truth": closure["truth"],
        "idempotent_reuse": idempotent_reuse,
        "resumed": resumed,
        "external_services": {
            "ai_research_workflow_9082": "stopped_by_design",
            "searxng": "stopped_by_design",
            "external_api_called": False,
            "real_provider_called": False,
        },
    }


def _write_json_once(path: Path, value: dict[str, Any]) -> None:
    if path.is_file():
        if _read_json(path) != value:
            raise ValueError(f"closure artifact drift: {path.name}")
        return
    _write_json(path, value)


def _write_bytes_once(path: Path, value: bytes) -> None:
    if path.is_file():
        if path.read_bytes() != value:
            raise ValueError(f"closure binary fixture drift: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
