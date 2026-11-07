"""Thin QRP bridge to ARW's canonical model-gateway consumer."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Callable


# Published optional-dependency snapshots are provenance only, never runtime gates.
ARW_CONSUMER_COMMIT = "075414087f92ed7f64dd4b8bf86aef76275ce343"
CANONICAL_GATEWAY_COMMIT = "c5f3ec49644453e0cddb56350e3b243b49e0f7da"
EXPECTED_EMBEDDING_RECEIPT_SCHEMA = "ai_research_workflow.embedding_candidate_receipt.v1"
EXPECTED_RECEIPT_SCHEMA = "ai_research_workflow.model_assist_receipt.v1"
EXPECTED_ARW_CONSUMER_CONTRACT_SCHEMA = "ai_research_workflow.gateway_consumer_contract.v1"
EXPECTED_GATEWAY_SEMANTIC_CONTRACT_SHA256 = "f9bf3bab27e767b093a761da5e04760b097a29c8e60aaee00f5b1ffe120bafa5"
ARW_COMPATIBLE_VERSION_RANGE = {
    "minimum_inclusive": "0.1.0",
    "maximum_exclusive": "0.2.0",
}
ARW_CONTRACT_COMPATIBLE_VERSION_RANGE = {
    "minimum_inclusive": "1.0.0",
    "maximum_exclusive": "2.0.0",
}
GATEWAY_COMPATIBLE_VERSION_RANGE = {
    "minimum_inclusive": "0.2.0",
    "maximum_exclusive": "0.4.0",
}
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+].*)?$")
PURPOSE_TASKS = {
    "planning": "research_query",
    "guarded_answer": "controlled_summary",
    "visual_evidence_candidate": "visual_claim_assist",
}


def run_gateway_model_assist(
    root: str | Path,
    *,
    profile: dict[str, Any],
    route: dict[str, Any],
    consent: dict[str, Any],
    purpose: str,
    request_id: str,
    max_estimated_cost_usd: float,
    ledger_path: str | Path | None = None,
    receipt_path: str | Path | None = None,
    transport: Any | None = None,
    secret_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Delegate one explicit model call to ARW without touching research truth."""
    task = PURPOSE_TASKS.get(purpose)
    if task is None:
        return _blocked_status(purpose=purpose, error_class="unsupported_purpose")
    if not request_id:
        return _blocked_status(purpose=purpose, error_class="request_id_missing")

    root_path = Path(root)
    truth_before = _truth_snapshot(root_path)
    receipt_dir = root_path / "model-assist-receipts"
    safe_request_key = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:24]
    selected_receipt = Path(receipt_path) if receipt_path else receipt_dir / f"{safe_request_key}.json"
    selected_ledger = Path(ledger_path) if ledger_path else receipt_dir / "gateway-ledger.json"

    try:
        runner = _load_arw_runner()
        result = runner(
            profile=profile,
            route=route,
            consent=consent,
            task=task,
            request_id=request_id,
            max_estimated_cost_usd=max_estimated_cost_usd,
            ledger_path=selected_ledger,
            receipt_path=selected_receipt,
            consumer_id="qrp",
            transport=transport,
            secret_resolver=secret_resolver,
        )
    except (ImportError, OSError, RuntimeError, TimeoutError, ValueError):
        if _truth_snapshot(root_path) != truth_before:
            return _blocked_status(purpose=purpose, error_class="research_truth_drift_detected")
        return _blocked_status(purpose=purpose, error_class="arw_consumer_unavailable")

    if _truth_snapshot(root_path) != truth_before:
        return _blocked_status(purpose=purpose, error_class="research_truth_drift_detected")

    if not _valid_delegated_receipt(
        result,
        task=task,
        profile=profile,
        route=route,
        consent=consent,
        request_id=request_id,
        max_estimated_cost_usd=max_estimated_cost_usd,
    ):
        return _blocked_status(purpose=purpose, error_class="arw_contract_drift")
    return result


def _load_arw_runner() -> Callable[..., dict[str, Any]]:
    from research_workflow import model_gateway

    _validate_arw_consumer_contract(model_gateway.consumer_contract_manifest())
    if model_gateway.RECEIPT_SCHEMA != EXPECTED_RECEIPT_SCHEMA:
        raise RuntimeError("ARW receipt schema drift")
    if "qrp" not in model_gateway.SUPPORTED_CONSUMERS:
        raise RuntimeError("ARW no longer accepts the QRP consumer")
    if not set(PURPOSE_TASKS.values()) <= model_gateway.SUPPORTED_TASKS:
        raise RuntimeError("ARW no longer supports the delegated QRP tasks")
    return model_gateway.run_model_assist


def _validate_arw_consumer_contract(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("ARW consumer contract is unavailable")
    payload = dict(value)
    claimed_hash = payload.pop("contract_sha256", None)
    if claimed_hash != _canonical_hash(payload):
        raise RuntimeError("ARW consumer contract hash drift")
    if value.get("schema") != EXPECTED_ARW_CONSUMER_CONTRACT_SCHEMA:
        raise RuntimeError("ARW consumer contract schema drift")
    _require_compatible_version(
        value.get("contract_version"),
        ARW_CONTRACT_COMPATIBLE_VERSION_RANGE,
        label="ARW consumer contract",
    )
    _require_compatible_version(
        value.get("package_version"),
        ARW_COMPATIBLE_VERSION_RANGE,
        label="ARW package",
    )
    receipts = value.get("receipt_schemas") or {}
    if receipts != {
        "model_assist": EXPECTED_RECEIPT_SCHEMA,
        "embedding_candidate": EXPECTED_EMBEDDING_RECEIPT_SCHEMA,
    }:
        raise RuntimeError("ARW receipt contract drift")
    if "qrp" not in set(value.get("consumers") or []):
        raise RuntimeError("ARW QRP delegation contract is missing")
    if not (set(PURPOSE_TASKS.values()) | {"embedding_candidate"}) <= set(value.get("tasks") or []):
        raise RuntimeError("ARW delegated task contract drift")
    gateway = value.get("gateway") or {}
    if not (
        gateway.get("compatible_version_range") == GATEWAY_COMPATIBLE_VERSION_RANGE
        and gateway.get("semantic_contract_sha256") == EXPECTED_GATEWAY_SEMANTIC_CONTRACT_SHA256
        and gateway.get("git_commit_role") == "provenance_only"
    ):
        raise RuntimeError("ARW Gateway contract drift")
    if value.get("truth_boundary") != {
        "research_truth_effect": "none",
        "evidence_status_change": "none",
        "candidate_only": True,
        "silent_fallback_allowed": False,
    }:
        raise RuntimeError("ARW research truth boundary drift")
    return value


def _require_compatible_version(value: object, version_range: dict[str, str], *, label: str) -> None:
    parsed = _parse_version(value)
    minimum = _parse_version(version_range["minimum_inclusive"])
    maximum = _parse_version(version_range["maximum_exclusive"])
    if parsed < minimum or parsed >= maximum:
        raise RuntimeError(f"{label} is outside the compatible range")


def _parse_version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise RuntimeError("semantic version is missing")
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise RuntimeError("semantic version is invalid")
    return tuple(int(part) for part in match.groups())


def _valid_delegated_receipt(
    value: object,
    *,
    task: str,
    profile: dict[str, Any],
    route: dict[str, Any],
    consent: dict[str, Any],
    request_id: str,
    max_estimated_cost_usd: float,
) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        expected_fingerprint = _canonical_hash(
            {
                "profile": profile,
                "route": route,
                "consent": consent,
                "task": task,
                "request_id": request_id,
                "max_estimated_cost_usd": max_estimated_cost_usd,
                "consumer_id": "qrp",
            }
        )
    except (TypeError, ValueError):
        return False
    if (
        value.get("request_id") != request_id
        or value.get("request_fingerprint") != expected_fingerprint
    ):
        return False
    gateway_contract = value.get("gateway_contract")
    if not isinstance(gateway_contract, dict):
        return False
    if not (
        gateway_contract.get("compatibility_status") in {"verified", "unavailable"}
        and gateway_contract.get("compatibility_basis") == "semantic_contract_not_git_identity"
        and gateway_contract.get("commit_is_compatibility_gate") is False
        and gateway_contract.get("version_is_compatibility_gate") is True
        and gateway_contract.get("version_role") == "range_gate_and_provenance"
        and gateway_contract.get("compatible_version_range") == GATEWAY_COMPATIBLE_VERSION_RANGE
        and gateway_contract.get("semantic_contract_sha256") == EXPECTED_GATEWAY_SEMANTIC_CONTRACT_SHA256
        and gateway_contract.get("automatic_fallback_allowed") is False
        and gateway_contract.get("automatic_retry_allowed") is False
    ):
        return False
    if value.get("status") == "candidate":
        if value.get("ok") is not True or value.get("model_output_status") != "candidate_only":
            return False
        if gateway_contract.get("compatibility_status") != "verified":
            return False
    elif value.get("status") == "blocked":
        if value.get("ok") is not False or value.get("model_output_status") != "unavailable":
            return False
    else:
        return False
    execution_result = value.get("execution_result")
    if execution_result is not None:
        if not isinstance(execution_result, dict):
            return False
        if execution_result.get("schema") != gateway_contract.get("result_schema"):
            return False
        audit = execution_result.get("redacted_audit")
        if not isinstance(audit, dict) or audit.get("automatic_fallback_used") is not False:
            return False
    return (
        value.get("schema") == EXPECTED_RECEIPT_SCHEMA
        and value.get("consumer_id") == "qrp"
        and value.get("task") == task
        and value.get("research_truth_effect") == "none"
        and value.get("evidence_status_change") == "none"
        and value.get("automatic_fallback_allowed") is False
        and value.get("automatic_retry_allowed") is False
    )


def _blocked_status(*, purpose: str, error_class: str) -> dict[str, Any]:
    return {
        "schema": "question_research_poc.model_assist_bridge_status.v1",
        "ok": False,
        "status": "blocked",
        "purpose": purpose,
        "error_class": error_class,
        "error_message": "QRP model assistance failed closed",
        "delegated_consumer": "ai-research-workflow",
        "delegated_consumer_commit": ARW_CONSUMER_COMMIT,
        "gateway_commit": CANONICAL_GATEWAY_COMMIT,
        "commit_role": "provenance_only",
        "commit_is_compatibility_gate": False,
        "profile_ref": None,
        "route_receipt": None,
        "consent_receipt": None,
        "execution_result": None,
        "model_output_status": "unavailable",
        "research_truth_effect": "none",
        "evidence_status_change": "none",
        "human_review_required": True,
        "automatic_fallback_allowed": False,
        "automatic_retry_allowed": False,
    }


def run_gateway_embedding_candidate(
    root: str | Path,
    *,
    artifact_paths: list[str | Path],
    purpose: str,
    request_id: str,
    receipt_path: str | Path | None = None,
    mime_types: list[str] | None = None,
    embedding_python: str | Path | None = None,
    embedding_model: str | Path | None = None,
    owner_output_dir: str | Path | None = None,
    embedding_device: str = "cpu",
    expected_dimensions: int = 384,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Delegate owner-receipt validation to ARW without touching QRP truth."""
    if not request_id or not purpose:
        return _embedding_blocked_status(error_class="request_contract_missing")
    root_path = Path(root)
    truth_before = _truth_snapshot(root_path)
    safe_request_key = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:24]
    selected_receipt = (
        Path(receipt_path)
        if receipt_path
        else root_path / "embedding-assist-receipts" / f"{safe_request_key}.json"
    )
    try:
        runner = _load_arw_embedding_runner()
        result = runner(
            artifact_paths=artifact_paths,
            purpose=purpose,
            request_id=request_id,
            receipt_path=selected_receipt,
            consumer_id="qrp",
            mime_types=mime_types,
            embedding_python=embedding_python,
            embedding_model=embedding_model,
            owner_output_dir=owner_output_dir,
            embedding_device=embedding_device,
            expected_dimensions=expected_dimensions,
            timeout_seconds=timeout_seconds,
        )
    except (ImportError, OSError, RuntimeError, TimeoutError, ValueError):
        if _truth_snapshot(root_path) != truth_before:
            return _embedding_blocked_status(error_class="research_truth_drift_detected")
        return _embedding_blocked_status(error_class="arw_consumer_unavailable")
    if _truth_snapshot(root_path) != truth_before:
        return _embedding_blocked_status(error_class="research_truth_drift_detected")
    if not _valid_embedding_receipt(
        result,
        artifact_paths=artifact_paths,
        purpose=purpose,
        request_id=request_id,
        mime_types=mime_types,
        embedding_python=embedding_python,
        embedding_model=embedding_model,
        embedding_device=embedding_device,
        expected_dimensions=expected_dimensions,
        timeout_seconds=timeout_seconds,
    ):
        return _embedding_blocked_status(error_class="arw_contract_drift")
    return result


def _load_arw_embedding_runner() -> Callable[..., dict[str, Any]]:
    from research_workflow import embedding_gateway, model_gateway

    _validate_arw_consumer_contract(model_gateway.consumer_contract_manifest())
    if embedding_gateway.EMBEDDING_RECEIPT_SCHEMA != EXPECTED_EMBEDDING_RECEIPT_SCHEMA:
        raise RuntimeError("ARW embedding receipt schema drift")
    return embedding_gateway.run_embedding_candidate


def _valid_embedding_receipt(
    value: object,
    *,
    artifact_paths: list[str | Path],
    purpose: str,
    request_id: str,
    mime_types: list[str] | None,
    embedding_python: str | Path | None,
    embedding_model: str | Path | None,
    embedding_device: str,
    expected_dimensions: int,
    timeout_seconds: int,
) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("schema") != EXPECTED_EMBEDDING_RECEIPT_SCHEMA:
        return False
    if value.get("consumer_id") != "qrp" or value.get("task") != "embedding_candidate":
        return False
    if value.get("request_id") != request_id or not _is_sha256(value.get("request_fingerprint")):
        return False
    if value.get("research_truth_effect") != "none" or value.get("evidence_status_change") != "none":
        return False
    if value.get("automatic_fallback_allowed") is not False or value.get("automatic_retry_allowed") is not False:
        return False
    if any(field in value for field in ("claims", "verified_facts", "vectors")):
        return False
    if value.get("status") == "blocked":
        return bool(
            value.get("ok") is False
            and isinstance(value.get("error_class"), str)
            and bool(value.get("error_class"))
            and not value.get("candidate_refs")
            and value.get("execution_performed") is False
            and value.get("provider_called") is False
            and value.get("external_io_performed") is False
            and value.get("model_output_status") == "unavailable"
        )
    if value.get("status") == "candidate":
        truth = value.get("capability_truth")
        consent = value.get("consent_receipt")
        owner = value.get("owner_receipt")
        manifest = value.get("input_manifest")
        plan = value.get("owner_plan")
        gate = value.get("owner_gate")
        run_receipt = value.get("owner_run_receipt")
        runtime_binding = value.get("runtime_binding")
        route = value.get("route_receipt")
        profile = value.get("profile_ref")
        gateway_contract = value.get("gateway_contract")
        if not all(
            isinstance(item, dict)
            for item in (
                truth,
                consent,
                owner,
                manifest,
                plan,
                gate,
                run_receipt,
                runtime_binding,
                route,
                profile,
                gateway_contract,
            )
        ):
            return False
        if not _valid_embedding_manifest(
            manifest,
            artifact_paths=artifact_paths,
            purpose=purpose,
            mime_types=mime_types,
        ):
            return False
        if not _valid_embedding_route_bundle(plan, gate, manifest=manifest):
            return False
        if not (
            route.get("plan_id") == plan.get("plan_id")
            and route.get("plan_revision") == plan.get("plan_revision")
            and route.get("owner_gate_receipt_hash") == gate.get("gate_revision")
            and profile
            == {
                "mode": "owner_adapter",
                "adapter_id": "sentence-transformers-local",
                "capability": "embedding",
            }
        ):
            return False
        if not (
            consent.get("status") == "granted_local"
            and consent.get("local_execution_authorized") is True
            and consent.get("provider_call_authorized") is False
            and consent.get("external_io_authorized") is False
            and consent.get("owner_gate_receipt_hash") == gate.get("gate_revision")
            and consent.get("input_manifest_hash") == manifest.get("manifest_revision")
        ):
            return False
        if not _valid_embedding_owner_receipt(owner, plan=plan, gate=gate):
            return False
        if not _valid_embedding_run_receipt(run_receipt, owner=owner, plan=plan, gate=gate):
            return False
        output = owner.get("output")
        candidates = value.get("candidate_refs")
        evidence_refs = value.get("evidence_refs")
        if not isinstance(output, dict) or not isinstance(candidates, list) or len(candidates) != 1:
            return False
        if not isinstance(evidence_refs, list) or len(evidence_refs) != len(manifest["artifacts"]):
            return False
        expected_candidate = {**output, "evidence_status": "candidate"}
        expected_evidence = [{**row, "evidence_status": "candidate"} for row in manifest["artifacts"]]
        if candidates[0] != expected_candidate or evidence_refs != expected_evidence:
            return False
        if any("vectors" in ref for ref in candidates if isinstance(ref, dict)):
            return False
        if not _valid_embedding_runtime_binding(
            runtime_binding,
            output=output,
            embedding_python=embedding_python,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
            expected_dimensions=expected_dimensions,
            timeout_seconds=timeout_seconds,
        ):
            return False
        expected_fingerprint = _canonical_hash(
            {
                "consumer_id": "qrp",
                "request_id": request_id,
                "purpose": purpose,
                "manifest_revision": manifest["manifest_revision"],
                "execution_mode": "gateway_owner_run_local",
                "runtime_binding": runtime_binding,
            }
        )
        if value.get("request_fingerprint") != expected_fingerprint:
            return False
        return bool(
            value.get("ok") is True
            and value.get("model_output_status") == "candidate_only"
            and value.get("execution_performed") is True
            and value.get("provider_called") is False
            and value.get("external_io_performed") is False
            and value.get("human_review_required") is True
            and truth.get("contract_ready") is True
            and truth.get("runtime_ready") is True
            and truth.get("fresh_e2e_pass") is True
            and truth.get("real_usage_proof") is False
            and truth.get("current_online") is False
            and gateway_contract.get("commit_role") == "provenance_only"
            and gateway_contract.get("commit_is_compatibility_gate") is False
            and gateway_contract.get("version_is_compatibility_gate") is True
            and gateway_contract.get("compatible_version_range") == GATEWAY_COMPATIBLE_VERSION_RANGE
            and gateway_contract.get("semantic_contract_sha256")
            == EXPECTED_GATEWAY_SEMANTIC_CONTRACT_SHA256
        )
    return False


def _valid_embedding_manifest(
    manifest: dict[str, Any],
    *,
    artifact_paths: list[str | Path],
    purpose: str,
    mime_types: list[str] | None,
) -> bool:
    if not (
        manifest.get("schema") == "model_provider_gateway.owner_input_manifest.v1"
        and manifest.get("purpose") == purpose
        and manifest.get("data_classification") in {"synthetic_fixture", "public_fixture"}
        and manifest.get("external_io_authorized") is False
        and manifest.get("manifest_revision") == _canonical_revision(manifest, "manifest_revision")
    ):
        return False
    rows = manifest.get("artifacts")
    if not isinstance(rows, list) or len(rows) != len(artifact_paths):
        return False
    if mime_types is not None and len(mime_types) != len(artifact_paths):
        return False
    try:
        for index, (row, raw_path) in enumerate(zip(rows, artifact_paths, strict=True)):
            path = Path(raw_path).expanduser().resolve()
            expected_mime = (
                mime_types[index]
                if mime_types is not None
                else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            ).lower()
            if not (
                path.is_file()
                and row.get("bytes") == path.stat().st_size
                and row.get("sha256") == _sha256_file(path)
                and row.get("mime_type") == expected_mime
                and row.get("purpose") == purpose
            ):
                return False
    except OSError:
        return False
    return True


def _valid_embedding_runtime_binding(
    runtime_binding: dict[str, Any],
    *,
    output: dict[str, Any],
    embedding_python: str | Path | None,
    embedding_model: str | Path | None,
    embedding_device: str,
    expected_dimensions: int,
    timeout_seconds: int,
) -> bool:
    if embedding_python is None or embedding_model is None:
        return False
    python_path = Path(embedding_python).expanduser().resolve()
    modules_path = Path(embedding_model).expanduser().resolve() / "modules.json"
    try:
        if not python_path.is_file() or not modules_path.is_file():
            return False
        runtime_sha256 = _sha256_file(python_path)
        model_revision = _sha256_file(modules_path)
    except OSError:
        return False
    return bool(
        runtime_binding.get("runtime_path_provided") is True
        and runtime_binding.get("runtime_sha256") == runtime_sha256
        and runtime_binding.get("model_path_provided") is True
        and runtime_binding.get("model_revision") == model_revision
        and runtime_binding.get("model_revision") == output.get("model_revision")
        and runtime_binding.get("model_source") == "explicit_local_files_only"
        and runtime_binding.get("device") == embedding_device
        and runtime_binding.get("expected_dimensions") == expected_dimensions
        and runtime_binding.get("expected_dimensions") == output.get("dimensions")
        and runtime_binding.get("timeout_seconds") == timeout_seconds
    )


def _valid_embedding_route_bundle(
    plan: dict[str, Any],
    gate: dict[str, Any],
    *,
    manifest: dict[str, Any],
) -> bool:
    if not (
        plan.get("schema") == "model_provider_gateway.owner_capability_plan.v1"
        and plan.get("consumer_id") == "qrp"
        and plan.get("capability") == "embedding"
        and plan.get("adapter_id") == "sentence-transformers-local"
        and plan.get("execution_mode") == "owner_adapter"
        and plan.get("input_manifest_hash") == manifest.get("manifest_revision")
        and plan.get("execution_authorized") is False
        and plan.get("provider_upload_authorized") is False
        and plan.get("owner_native_gate_required") is True
        and plan.get("automatic_fallback_allowed") is False
        and plan.get("automatic_retry_allowed") is False
        and plan.get("plan_revision") == _canonical_revision(plan, "plan_revision")
    ):
        return False
    return bool(
        gate.get("schema") == "model_provider_gateway.owner_capability_gate.v1"
        and gate.get("scope") == "local_synthetic_or_public_fixture"
        and gate.get("plan_id") == plan.get("plan_id")
        and gate.get("plan_revision") == plan.get("plan_revision")
        and gate.get("capability") == plan.get("capability")
        and gate.get("adapter_id") == plan.get("adapter_id")
        and gate.get("input_manifest_hash") == manifest.get("manifest_revision")
        and gate.get("local_execution_authorized") is True
        and gate.get("provider_call_authorized") is False
        and gate.get("external_io_authorized") is False
        and gate.get("automatic_fallback_allowed") is False
        and gate.get("automatic_retry_allowed") is False
        and gate.get("gate_revision") == _canonical_revision(gate, "gate_revision")
    )


def _valid_embedding_owner_receipt(
    owner: dict[str, Any],
    *,
    plan: dict[str, Any],
    gate: dict[str, Any],
) -> bool:
    output = owner.get("output")
    return bool(
        owner.get("schema") == "model_provider_gateway.owner_capability_receipt.v1"
        and owner.get("status") == "completed"
        and owner.get("plan_id") == plan.get("plan_id")
        and owner.get("plan_revision") == plan.get("plan_revision")
        and owner.get("consumer_id") == "qrp"
        and owner.get("capability") == "embedding"
        and owner.get("adapter_id") == "sentence-transformers-local"
        and owner.get("input_manifest_hash") == plan.get("input_manifest_hash")
        and owner.get("owner_gate_receipt_hash") == gate.get("gate_revision")
        and owner.get("provider_called") is False
        and owner.get("external_io_performed") is False
        and owner.get("automatic_fallback_used") is False
        and owner.get("error") is None
        and isinstance(output, dict)
        and output.get("kind") == "embedding_manifest"
        and _is_sha256(output.get("vectors_sha256"))
        and _is_sha256(output.get("model_revision"))
        and isinstance(output.get("dimensions"), int)
        and output.get("dimensions") > 0
        and isinstance(output.get("item_count"), int)
        and output.get("item_count") > 0
    )


def _valid_embedding_run_receipt(
    run_receipt: dict[str, Any],
    *,
    owner: dict[str, Any],
    plan: dict[str, Any],
    gate: dict[str, Any],
) -> bool:
    runtime = run_receipt.get("runtime")
    return bool(
        run_receipt.get("schema") == "model_provider_gateway.owner_runtime_run_report.v1"
        and run_receipt.get("status") == "completed"
        and run_receipt.get("capability") == "embedding"
        and run_receipt.get("adapter_id") == "sentence-transformers-local"
        and run_receipt.get("plan_revision") == plan.get("plan_revision")
        and run_receipt.get("input_manifest_hash") == plan.get("input_manifest_hash")
        and run_receipt.get("gate_revision") == gate.get("gate_revision")
        and run_receipt.get("receipt_hash") == _canonical_hash(owner)
        and run_receipt.get("error") is None
        and isinstance(runtime, dict)
        and runtime.get("execution_location") == "local"
        and runtime.get("provider_called") is False
        and runtime.get("external_io_performed") is False
        and runtime.get("automatic_retry_count") == 0
        and runtime.get("automatic_fallback_used") is False
    )


def _canonical_revision(value: dict[str, Any], revision_key: str) -> str:
    return _canonical_hash({key: item for key, item in value.items() if key != revision_key})


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _embedding_blocked_status(*, error_class: str) -> dict[str, Any]:
    return {
        "schema": "question_research_poc.embedding_assist_bridge_status.v1",
        "ok": False,
        "status": "blocked",
        "error_class": error_class,
        "error_message": "QRP embedding assistance failed closed",
        "delegated_consumer": "ai-research-workflow",
        "delegated_consumer_commit": ARW_CONSUMER_COMMIT,
        "gateway_commit": CANONICAL_GATEWAY_COMMIT,
        "commit_role": "provenance_only",
        "commit_is_compatibility_gate": False,
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


def _truth_snapshot(root: Path) -> dict[str, bytes | None]:
    names = (
        "research.json",
        "sources.jsonl",
        "source-reviews.jsonl",
        "claims.jsonl",
        "evidence.jsonl",
        "reviews.jsonl",
        "graph-candidates.jsonl",
        "answer-drafts.jsonl",
    )
    return {name: (root / name).read_bytes() if (root / name).is_file() else None for name in names}
