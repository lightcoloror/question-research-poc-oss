from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT.parent / "artifact-lifecycle-core"
sys.path.insert(0, str(CORE_ROOT))
import artifact_lifecycle_core as core
import research_evidence_adapter as adapter


CONFIG = REPO_ROOT / "artifact-lifecycle" / "research-evidence-lifecycle.v1.json"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "artifact-lifecycle" / "research-evidence.v1.json"


def _isolated_root(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    config = repo / "artifact-lifecycle" / CONFIG.name
    config.parent.mkdir(parents=True)
    shutil.copy2(CONFIG, config)
    root = repo / "tests" / "fixtures" / "artifact-lifecycle" / "research-evidence"
    for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["files"]:
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"], encoding="utf-8")
    return config, root


def _manifest(config: Path, root: Path, tmp_path: Path) -> dict:
    return adapter.build_manifest(config, root, "qrp-lifecycle-closure-001", tmp_path / "checkpoint.sqlite3")


def test_qrp_lifecycle_manifest_is_stable_and_protects_references(tmp_path: Path) -> None:
    config, root = _isolated_root(tmp_path)
    first = _manifest(config, root, tmp_path)
    second = _manifest(config, root, tmp_path)
    assert first["manifest_sha256"] == second["manifest_sha256"]
    records = {item["path"]: item for item in first["artifacts"]}
    assert records["evidence/evidence-bundle.json"]["pin"] is True
    assert records["answers/guarded-answer.json"]["artifact_role"] == "final_deliverable"
    assert records["unknown/unclassified.bin"]["referenced_by"] == ["unknown_reference"]


def test_qrp_lifecycle_plan_drift_and_synthetic_restore(tmp_path: Path) -> None:
    config, root = _isolated_root(tmp_path)
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    manifest = _manifest(config, root, tmp_path)
    plan = core.plan_operation(manifest, root, quarantine, "quarantine", owner_state="idle_confirmed", process_state="idle_confirmed", dispatch_state="none_active")
    candidate = next(item for item in plan["entries"] if item["source_path"].endswith("failed-retrieval.tmp"))
    protected = next(item for item in plan["entries"] if item["source_path"].endswith("guarded-answer.json"))
    assert candidate["eligible"] is True
    assert "artifact_pinned" in protected["blocking_gates"]
    assert core.verify_plan(plan, manifest, root, quarantine)["ok"] is True
    (root / "cache" / "failed-retrieval.tmp").write_text("drift", encoding="utf-8")
    assert core.verify_plan(plan, manifest, root, quarantine)["ok"] is False
    manifest = _manifest(config, root, tmp_path)
    plan = core.plan_operation(manifest, root, quarantine, "quarantine", owner_state="idle_confirmed", process_state="idle_confirmed", dispatch_state="none_active")
    now = dt.datetime.now(dt.timezone.utc)
    approval = {"schema_version": core.APPROVAL_SCHEMA_VERSION, "operation": "quarantine", "plan_sha256": plan["plan_sha256"], "approved": True, "approved_by": "synthetic-test", "approved_at": now.isoformat(), "expires_at": (now + dt.timedelta(minutes=5)).isoformat()}
    receipt = core.apply_quarantine(plan, manifest, root, quarantine, approval, tmp_path / "quarantine-receipt.json")
    core.restore_from_receipt(receipt, plan, root, quarantine, tmp_path / "restore-receipt.json")
    assert (root / "cache" / "failed-retrieval.tmp").is_file()


def test_qrp_embedding_preflight_fails_closed_under_low_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, root = _isolated_root(tmp_path)
    monkeypatch.setattr(core.shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(total=1000, used=900, free=100))
    result = adapter.preflight(config, root, "embedding")
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["blocked_low_disk"]
