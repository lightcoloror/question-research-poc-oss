from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "owner_manifest_doctor.py"
SPEC = importlib.util.spec_from_file_location("qrp_owner_manifest_doctor", SCRIPT)
assert SPEC and SPEC.loader
DOCTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCTOR)
TOOL_ID = "question-research-poc"


def _temp_dir() -> Path:
    # Adapted for public use: never create runtime state inside the repository.
    # A unique directory is created directly under the approved TEST_TMP_ROOT
    # after a nested-write refusal observed in one Windows environment.
    # The cause of that refusal was not established; no ACL change is made.
    base = Path(
        os.environ.get(
            "TEST_TMP_ROOT",
            str(Path(tempfile.gettempdir()) / "qrp-owner-portability"),
        )
    )
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(64):
        candidate = base / f"qrp-owner-{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("unable to allocate a unique test directory")


def _relocate(parent: Path) -> Path:
    target = parent / "relocated"
    manifest = json.loads((ROOT / DOCTOR.MANIFEST_NAME).read_text(encoding="utf-8"))
    paths = {DOCTOR.MANIFEST_NAME}
    for group in ("no_write_checks", "runtime_checks"):
        paths.update(item["path"] for item in manifest["provenance"][group])
    for relative in paths:
        source = ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return target


def _receipt(parent: Path, checked_at: datetime | None = None) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    artifact = parent / "synthetic-result.json"
    artifact.write_text('{"candidate_only":true}\n', encoding="utf-8")
    receipt = parent / "receipt.json"
    receipt.write_text(json.dumps({
        "schema_version": DOCTOR.RECEIPT_SCHEMA,
        "tool_id": TOOL_ID,
        "status": "passed",
        "checked_at": (checked_at or datetime.now(timezone.utc)).isoformat(),
        "artifact": {"path": artifact.name, "sha256": DOCTOR.sha256_file(artifact)},
        "truth": {"fresh_e2e_pass": True, "real_usage_proof": False, "current_online": False},
    }), encoding="utf-8")
    return receipt


def test_relocated_doctor_is_no_write_offline_and_idempotent() -> None:
    manifest = json.loads((ROOT / DOCTOR.MANIFEST_NAME).read_text(encoding="utf-8"))
    for group in ("no_write_checks", "runtime_checks"):
        items = manifest["provenance"][group]
        assert items
        for item in items:
            relative = Path(item["path"])
            assert not relative.is_absolute()
            assert ".." not in relative.parts
            assert item.get("kind", "file") == "file"
            assert (ROOT / relative).is_file()
    assert any(
        item["path"] == "src/question_research_poc/cli.py"
        for item in manifest["provenance"]["runtime_checks"]
    )
    temp = _temp_dir()
    try:
        root = _relocate(temp)
        before = {p.relative_to(root): DOCTOR.sha256_file(p) for p in root.rglob("*") if p.is_file()}
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            first = DOCTOR.doctor(root, TOOL_ID)
            second = DOCTOR.doctor(root, TOOL_ID)
        after = {p.relative_to(root): DOCTOR.sha256_file(p) for p in root.rglob("*") if p.is_file()}
        assert first == second
        assert before == after
        assert first["status"] == "ready_metadata_only"
        assert first["truth"]["contract_ready"]["value"] is True
        assert first["truth"]["runtime_ready"]["value"] is True
        assert first["truth"]["fresh_e2e_pass"]["value"] is None
        assert first["truth"]["real_usage_proof"]["value"] is False
        assert first["truth"]["current_online"]["value"] is False
        assert first["runtime_checks_semantics"] == "static_file_presence_only_not_execution"
        assert first["evidence_qualification"]["runtime_executed"] is False
        assert first["evidence_qualification"]["receipt_can_grant_publish_or_permissions"] is False
        assert first["publish_authorized"] is False
        assert first["permissions_granted"] is False
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def test_current_receipt_passes_but_stale_hash_drift_and_corruption_fail_closed() -> None:
    temp = _temp_dir()
    try:
        root = _relocate(temp)
        current = _receipt(temp / "current")
        current_result = DOCTOR.doctor(root, TOOL_ID, current)["truth"]["fresh_e2e_pass"]
        assert current_result["value"] is True
        assert current_result["qualification"]["trusted_as_instruction"] is False
        assert current_result["qualification"]["proves"] == "artifact_sha256_and_time_window_only"
        stale = _receipt(temp / "stale", datetime.now(timezone.utc) - timedelta(hours=169))
        assert "receipt_stale" in DOCTOR.doctor(root, TOOL_ID, stale)["truth"]["fresh_e2e_pass"]["reason_codes"]
        future = _receipt(temp / "future", datetime.now(timezone.utc) + timedelta(days=3650))
        assert "receipt_future_timestamp" in DOCTOR.doctor(root, TOOL_ID, future)["truth"]["fresh_e2e_pass"]["reason_codes"]
        (current.parent / "synthetic-result.json").write_text("drift", encoding="utf-8")
        assert "artifact_hash_drift" in DOCTOR.doctor(root, TOOL_ID, current)["truth"]["fresh_e2e_pass"]["reason_codes"]
        manifest_path = root / DOCTOR.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["executionAuthority"] = "execute"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(DOCTOR.DoctorError, match="execute"):
            DOCTOR.doctor(root, TOOL_ID)
        with pytest.raises(DOCTOR.DoctorError, match="escape"):
            DOCTOR.resolve_inside(root, "../escape")
    finally:
        shutil.rmtree(temp, ignore_errors=True)
