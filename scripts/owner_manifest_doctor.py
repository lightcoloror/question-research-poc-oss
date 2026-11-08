from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MANIFEST_NAME = "agent-tool-manifest.v1.json"
MANIFEST_SCHEMA = "agent-tool-manifest.v1"
RECEIPT_SCHEMA = "agent-tool-owner-synthetic-receipt.v1"
DOCTOR_SCHEMA = "agent-tool-owner-doctor.v1"
ERROR_SCHEMA = "agent-tool-owner-doctor-error.v1"
DEFAULT_TTL_HOURS = 168
MAX_FUTURE_SKEW_SECONDS = 60
CHECK_KINDS = ("file", "directory")

_MACHINE_PATH = re.compile(r"(?i)(?<![a-z])[a-z]:[/\\]|/Users/|/home/")


class DoctorError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise DoctorError("missing_file", str(path)) from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise DoctorError("invalid_encoding", f"{path}:{exc}") from exc
    except json.JSONDecodeError as exc:
        raise DoctorError("invalid_json", f"{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise DoctorError("json_object_required", str(path))
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise DoctorError("path_invalid", repr(relative))
    candidate_path = Path(relative)
    if candidate_path.is_absolute():
        raise DoctorError("absolute_path_forbidden", relative)
    resolved_root = root.resolve()
    candidate = (resolved_root / candidate_path).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise DoctorError("path_escape", relative)
    return candidate


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DoctorError("manifest_invalid_type", f"{label}:object_required")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DoctorError("manifest_invalid_type", f"{label}:list_required")
    return value


def _validate_check_list(
    value: Any, label: str, seen_ids: set[str]
) -> list[dict[str, Any]]:
    items = _list(value, label)
    if not items:
        raise DoctorError("manifest_checklist_empty", label)
    checked: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        item = _object(raw, f"{label}[{index}]")
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise DoctorError("manifest_check_id_invalid", f"{label}[{index}].id")
        if raw_id != raw_id.strip():
            raise DoctorError(
                "manifest_check_id_whitespace", f"{label}[{index}].id"
            )
        check_id = raw_id
        if check_id in seen_ids:
            raise DoctorError("duplicate_check_id", check_id)
        seen_ids.add(check_id)
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise DoctorError("manifest_check_path_invalid", f"{label}[{index}].path")
        kind = item.get("kind", "file")
        if not isinstance(kind, str) or kind not in CHECK_KINDS:
            raise DoctorError("manifest_check_kind_invalid", f"{label}[{index}].kind")
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise DoctorError(
                "manifest_check_required_invalid", f"{label}[{index}].required"
            )
        contains = item.get("contains")
        if contains is not None and not isinstance(contains, str):
            raise DoctorError(
                "manifest_check_contains_invalid", f"{label}[{index}].contains"
            )
        checked.append(
            {
                "id": check_id.strip(),
                "kind": kind,
                "path": path,
                "required": required,
                "contains": contains,
            }
        )
    if not any(item["required"] and item["kind"] == "file" for item in checked):
        raise DoctorError("manifest_checklist_no_required_file", label)
    return checked


def _validate_restore_sequence(value: Any) -> list[str]:
    # Recovery text is descriptive data only. It is validated for shape and
    # returned verbatim; the doctor never executes, evaluates or interpolates
    # it, and performs no process, shell, network or write action.
    if value is None:
        return []
    items = _list(value, "provenance.restore_sequence")
    entries: list[str] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, str) or not raw.strip():
            raise DoctorError(
                "manifest_restore_entry_invalid",
                f"provenance.restore_sequence[{index}]",
            )
        entries.append(raw)
    return entries


def _validate_manifest(payload: dict[str, Any], tool_id: str) -> dict[str, Any]:
    required = {
        "schema_version",
        "id",
        "manifest_version",
        "interfaces",
        "health",
        "provenance",
        "notTrustedAsInstruction",
        "executionAuthority",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise DoctorError("manifest_required_field_missing", ",".join(missing))
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise DoctorError(
            "manifest_schema_mismatch", str(payload.get("schema_version"))
        )
    manifest_id = payload.get("id")
    if not isinstance(manifest_id, str) or manifest_id != tool_id:
        raise DoctorError("manifest_tool_id_mismatch", str(manifest_id))
    version = payload.get("manifest_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise DoctorError("manifest_version_invalid", repr(version))
    if payload.get("notTrustedAsInstruction") is not True:
        raise DoctorError("manifest_trust_boundary_invalid", "notTrustedAsInstruction")
    if payload.get("executionAuthority") != "none_metadata_only":
        raise DoctorError(
            "manifest_execution_authority_invalid",
            str(payload.get("executionAuthority")),
        )
    health = _object(payload.get("health"), "health")
    if health.get("proves_current_online") is not False:
        raise DoctorError("manifest_online_claim_invalid", "health.proves_current_online")
    interfaces = _list(payload.get("interfaces"), "interfaces")
    if not interfaces:
        raise DoctorError("manifest_interfaces_empty", "interfaces")
    for index, raw in enumerate(interfaces):
        item = _object(raw, f"interfaces[{index}]")
        if not isinstance(item.get("id"), str) or not str(item.get("id")).strip():
            raise DoctorError("manifest_interface_invalid", f"interfaces[{index}].id")
        for key in ("module", "source_path"):
            if key in item and not isinstance(item[key], str):
                raise DoctorError(
                    "manifest_interface_invalid", f"interfaces[{index}].{key}"
                )
    if _MACHINE_PATH.search(json.dumps(interfaces, ensure_ascii=False)):
        raise DoctorError("machine_path_in_interface", "interfaces")
    provenance = _object(payload.get("provenance"), "provenance")
    if "registry_sha256" in provenance:
        raise DoctorError(
            "volatile_registry_hash_forbidden", "provenance.registry_sha256"
        )
    for name in ("no_write_checks", "runtime_checks"):
        if name not in provenance:
            raise DoctorError(
                "manifest_required_field_missing", f"provenance.{name}"
            )
    seen_ids: set[str] = set()
    contract = _validate_check_list(
        provenance["no_write_checks"], "provenance.no_write_checks", seen_ids
    )
    runtime = _validate_check_list(
        provenance["runtime_checks"], "provenance.runtime_checks", seen_ids
    )
    recovery = _validate_restore_sequence(provenance.get("restore_sequence"))
    return {"contract": contract, "runtime": runtime, "recovery": recovery}


def _validate_ttl(ttl_hours: Any) -> int:
    if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, int):
        raise DoctorError("invalid_ttl", repr(ttl_hours))
    if ttl_hours <= 0:
        raise DoctorError("invalid_ttl_nonpositive", str(ttl_hours))
    return ttl_hours


def _check_path(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    relative = str(item["path"])
    path = resolve_inside(root, relative)
    kind = item["kind"]
    exists = path.is_file() if kind == "file" else path.is_dir() if kind == "directory" else False
    contains = item.get("contains")
    content_matches = None
    if exists and contains is not None and path.is_file():
        content_matches = contains in path.read_text(encoding="utf-8", errors="replace")
    passed = exists and content_matches is not False
    return {
        "id": item["id"],
        "kind": kind,
        "path": relative.replace("\\", "/"),
        "required": item["required"],
        "status": "passed" if passed else "missing_or_mismatch",
    }


def _receipt_qualification() -> dict[str, Any]:
    return {
        "kind": "caller_declared_synthetic_receipt",
        "trusted_as_instruction": False,
        "proves": "artifact_sha256_and_time_window_only",
        "does_not_prove": [
            "owner_earned_execution",
            "real_usage",
            "current_online",
            "installed_wheel",
            "publication_or_ownership_rights",
        ],
    }


def _validate_receipt(
    receipt_path: Path | None, tool_id: str, ttl_hours: int
) -> dict[str, Any]:
    qualification = _receipt_qualification()
    if receipt_path is None:
        return {
            "value": None,
            "status": "not_assessed",
            "ttl_hours": ttl_hours,
            "reason_codes": ["synthetic_receipt_not_provided"],
            "qualification": qualification,
        }
    try:
        resolved_receipt = receipt_path.resolve()
        payload = read_json(resolved_receipt)
        reasons: list[str] = []
        if payload.get("schema_version") != RECEIPT_SCHEMA:
            reasons.append("receipt_schema_mismatch")
        if payload.get("tool_id") != tool_id:
            reasons.append("receipt_tool_id_mismatch")
        if payload.get("status") != "passed":
            reasons.append("receipt_status_invalid")
        truth = payload.get("truth")
        if not isinstance(truth, dict):
            reasons.append("receipt_truth_invalid")
        else:
            if truth.get("fresh_e2e_pass") is not True:
                reasons.append("receipt_truth_invalid")
            if truth.get("real_usage_proof") is not False:
                reasons.append("receipt_real_usage_claim_invalid")
            if truth.get("current_online") is not False:
                reasons.append("receipt_online_claim_invalid")
        artifact = payload.get("artifact")
        if not isinstance(artifact, dict):
            raise DoctorError("receipt_artifact_invalid", "artifact:object_required")
        artifact_relative = artifact.get("path")
        if not isinstance(artifact_relative, str) or not artifact_relative.strip():
            raise DoctorError("receipt_artifact_invalid", "artifact.path")
        artifact_path = resolve_inside(resolved_receipt.parent, artifact_relative)
        expected_sha = artifact.get("sha256")
        hash_matches = False
        if not isinstance(expected_sha, str) or re.fullmatch(
            r"[0-9a-f]{64}", expected_sha
        ) is None:
            reasons.append("receipt_artifact_hash_invalid")
        elif not artifact_path.is_file():
            reasons.append("receipt_artifact_missing")
        else:
            hash_matches = sha256_file(artifact_path) == expected_sha
            if not hash_matches:
                reasons.append("artifact_hash_drift")
        raw_checked_at = payload.get("checked_at")
        if not isinstance(raw_checked_at, str) or not raw_checked_at.strip():
            raise DoctorError("receipt_checked_at_invalid", "checked_at")
        try:
            checked_at = datetime.fromisoformat(raw_checked_at)
        except ValueError as exc:
            raise DoctorError("receipt_checked_at_invalid", raw_checked_at) from exc
        naive = checked_at.tzinfo is None
        if naive:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        checked_at_utc = checked_at.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        future = checked_at_utc > now + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
        if future:
            reasons.append("receipt_future_timestamp")
        expired = (now - checked_at_utc) > timedelta(hours=ttl_hours)
        if expired:
            reasons.append("receipt_stale")
        valid = not reasons
        return {
            "value": valid,
            "status": "passed_current" if valid else "rejected",
            "ttl_hours": ttl_hours,
            "reason_codes": reasons,
            "checked_at_utc": checked_at_utc.isoformat(),
            "checked_at_naive_utc_assumed": naive,
            "future_timestamp": future,
            "artifact_hash_matches": hash_matches,
            "qualification": qualification,
        }
    except (DoctorError, OSError, ValueError) as exc:
        return {
            "value": False,
            "status": "rejected",
            "ttl_hours": ttl_hours,
            "reason_codes": [getattr(exc, "code", "receipt_invalid")],
            "qualification": qualification,
        }


def doctor(
    root: Path,
    tool_id: str,
    receipt_path: Path | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> dict[str, Any]:
    ttl = _validate_ttl(ttl_hours)
    try:
        resolved_root = Path(root).resolve()
    except (TypeError, OSError) as exc:
        raise DoctorError("invalid_root", str(root)) from exc
    manifest_path = resolved_root / MANIFEST_NAME
    manifest = read_json(manifest_path)
    validated = _validate_manifest(manifest, tool_id)
    contract_checks = [
        _check_path(resolved_root, item) for item in validated["contract"]
    ]
    runtime_checks = [
        _check_path(resolved_root, item) for item in validated["runtime"]
    ]
    contract_failures = [
        item["id"]
        for item in contract_checks
        if item["required"] and item["status"] != "passed"
    ]
    runtime_failures = [
        item["id"]
        for item in runtime_checks
        if item["required"] and item["status"] != "passed"
    ]
    contract_ready = not contract_failures
    runtime_ready = contract_ready and not runtime_failures
    fresh = _validate_receipt(receipt_path, tool_id, ttl)
    status = (
        "ready_metadata_only"
        if contract_ready and runtime_ready
        else "blocked_contract"
        if not contract_ready
        else "blocked_runtime"
    )
    return {
        "schema_version": DOCTOR_SCHEMA,
        "tool_id": tool_id,
        "manifest_version": manifest["manifest_version"],
        "status": status,
        "truth": {
            "contract_ready": {
                "value": contract_ready,
                "status": "passed_current" if contract_ready else "blocked",
                "evidence": "static_required_file_presence",
            },
            "runtime_ready": {
                "value": runtime_ready,
                "status": "derived_local_static" if runtime_ready else "blocked",
                "evidence": "static_required_file_presence_not_execution",
            },
            "fresh_e2e_pass": fresh,
            "real_usage_proof": {
                "value": False,
                "status": "not_proved_by_synthetic_or_metadata",
            },
            "current_online": {"value": False, "status": "not_probed"},
        },
        "manifest": {
            "path": MANIFEST_NAME,
            "sha256": sha256_file(manifest_path),
            "valid": True,
        },
        "checks": {"contract": contract_checks, "runtime": runtime_checks},
        "runtime_checks_semantics": "static_file_presence_only_not_execution",
        "failures": {"contract": contract_failures, "runtime": runtime_failures},
        "recovery": validated["recovery"],
        "evidence_qualification": {
            "scope": "metadata_and_static_file_presence_only",
            "runtime_executed": False,
            "network_performed": False,
            "write_performed": False,
            "receipt_trusted_as_instruction": False,
            "receipt_can_grant_publish_or_permissions": False,
            "not_proof_of": [
                "installed_wheel_or_package_build",
                "real_research_or_model_use",
                "clinical_or_field_validity",
                "operating_system_or_platform_readiness",
                "publication_or_ownership_rights",
            ],
        },
        "publish_authorized": False,
        "permissions_granted": False,
        "runtime_probe_performed": False,
        "network_performed": False,
        "secret_values_read": False,
        "write_performed": False,
        "metadata_authorizes_execution": False,
        "silent_fallback": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Validate an owner manifest without network or writes."
    )
    result.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    result.add_argument("--tool-id", required=True)
    result.add_argument("--receipt", type=Path)
    result.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    result.add_argument("--format", choices=("json",), default="json")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = doctor(args.root, args.tool_id, args.receipt, args.ttl_hours)
    except DoctorError as exc:
        error = {
            "schema_version": ERROR_SCHEMA,
            "status": "blocked",
            "error": {"code": exc.code, "detail": str(exc)},
            "network_performed": False,
            "secret_values_read": False,
            "write_performed": False,
        }
        print(json.dumps(error, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ready_metadata_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
