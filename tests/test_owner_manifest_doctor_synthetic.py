"""Directed synthetic tests for the public owner manifest doctor.

Standard-library unittest only. The doctor module is loaded by relative file
path, so this file imports no candidate package. Every case uses the synthetic
public fixtures copied into a temporary directory under TEST_TMP_ROOT; nothing
outside that temporary directory is written. No network, subprocess, model,
service, install, Git or research action is performed.

Mocked boundaries are labelled where they are used: socket construction is
mocked to prove the no-network claim, restore-sequence text is checked to stay
data-only with no execution, and the symlink case explicitly skips when the
host lacks symlink privilege (set TEST_SYMLINK_KNOWN_UNAVAILABLE=1 to skip the
known-unavailable host case without retrying OS symlink creation).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "owner_manifest_doctor.py"
SPEC = importlib.util.spec_from_file_location(
    "qrp_owner_manifest_doctor_synthetic", SCRIPT
)
assert SPEC and SPEC.loader
DOCTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCTOR)
TOOL_ID = "question-research-poc"
MANIFEST = DOCTOR.MANIFEST_NAME


def _tmp_root() -> Path:
    configured = os.environ.get("TEST_TMP_ROOT")
    if configured:
        base = Path(configured)
    else:
        base = Path(tempfile.gettempdir()) / "qrp-owner-synthetic"
    base.mkdir(parents=True, exist_ok=True)
    return base


class DoctorSyntheticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = self._unique_dir(_tmp_root(), "qrp-doctor-")
        self.root = self._relocate()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def _unique_dir(self, base: Path, prefix: str) -> Path:
        # A nested-write refusal was observed in one Windows environment; its
        # cause was not established. Create each fixture directly under the
        # caller-selected TEST_TMP_ROOT without changing permissions.
        base.mkdir(parents=True, exist_ok=True)
        for _ in range(64):
            candidate = base / f"{prefix}{uuid.uuid4().hex}"
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            return candidate
        raise RuntimeError("unable to allocate a unique test directory")

    def _relocate(self) -> Path:
        target = self.temp / "repo"
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        paths = {MANIFEST}
        for group in ("no_write_checks", "runtime_checks"):
            paths.update(item["path"] for item in manifest["provenance"][group])
        for relative in paths:
            source = ROOT / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return target

    def _manifest(self) -> dict:
        return json.loads((self.root / MANIFEST).read_text(encoding="utf-8"))

    def _reset_manifest(self) -> None:
        shutil.copy2(ROOT / MANIFEST, self.root / MANIFEST)

    def _write_manifest(self, payload: object) -> None:
        (self.root / MANIFEST).write_text(json.dumps(payload), encoding="utf-8")

    def _edit_manifest(self, mutate) -> None:
        self._reset_manifest()
        payload = self._manifest()
        mutate(payload)
        self._write_manifest(payload)

    def _snapshot(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.root)): DOCTOR.sha256_file(path)
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def _assert_doctor_error(self, expected_code: str, **kwargs: object) -> None:
        with self.assertRaises(DOCTOR.DoctorError) as caught:
            DOCTOR.doctor(self.root, TOOL_ID, **kwargs)
        self.assertEqual(caught.exception.code, expected_code)

    def _fresh(self, receipt: Path) -> dict:
        return DOCTOR.doctor(self.root, TOOL_ID, receipt)["truth"]["fresh_e2e_pass"]

    def _write_receipt(self, directory: Path, **overrides: object) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / "synthetic-result.json"
        artifact.write_bytes(
            overrides.pop("artifact_bytes", b'{"candidate_only":true}\n')
        )
        payload = {
            "schema_version": overrides.pop(
                "schema_version", DOCTOR.RECEIPT_SCHEMA
            ),
            "tool_id": overrides.pop("tool_id", TOOL_ID),
            "status": overrides.pop("status", "passed"),
            "checked_at": overrides.pop("checked_at", None)
            or datetime.now(timezone.utc).isoformat(),
            "artifact": {
                "path": overrides.pop("artifact_path", "synthetic-result.json"),
                "sha256": overrides.pop(
                    "artifact_sha256", DOCTOR.sha256_file(artifact)
                ),
            },
            "truth": overrides.pop(
                "truth",
                {
                    "fresh_e2e_pass": True,
                    "real_usage_proof": False,
                    "current_online": False,
                },
            ),
        }
        self.assertFalse(overrides, f"unknown overrides: {overrides}")
        receipt = directory / "receipt.json"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        return receipt

    # ------------------------------------------------------------------- tests
    def test_01_relocated_public_copy_is_ready_offline_no_write_and_idempotent(
        self,
    ) -> None:
        before = self._snapshot()
        with mock.patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ), mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("network forbidden")
        ):
            first = DOCTOR.doctor(self.root, TOOL_ID)
            second = DOCTOR.doctor(self.root, TOOL_ID)
        after = self._snapshot()
        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertEqual(first["status"], "ready_metadata_only")
        self.assertTrue(first["truth"]["contract_ready"]["value"])
        self.assertTrue(first["truth"]["runtime_ready"]["value"])
        self.assertIsNone(first["truth"]["fresh_e2e_pass"]["value"])
        self.assertIn(
            "synthetic_receipt_not_provided",
            first["truth"]["fresh_e2e_pass"]["reason_codes"],
        )
        self.assertFalse(first["truth"]["real_usage_proof"]["value"])
        self.assertFalse(first["truth"]["current_online"]["value"])
        checks = first["checks"]["contract"] + first["checks"]["runtime"]
        self.assertTrue(checks)
        self.assertTrue(all(item["status"] == "passed" for item in checks))
        self.assertEqual(
            first["runtime_checks_semantics"],
            "static_file_presence_only_not_execution",
        )
        self.assertFalse(first["runtime_probe_performed"])
        self.assertFalse(first["network_performed"])
        self.assertFalse(first["write_performed"])
        self.assertFalse(first["metadata_authorizes_execution"])
        self.assertFalse(first["publish_authorized"])
        self.assertFalse(first["permissions_granted"])
        self.assertTrue(first["recovery"])
        self.assertTrue(all(isinstance(item, str) for item in first["recovery"]))

    def test_02_cli_ready_returns_zero_and_blocked_returns_two(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = DOCTOR.main(["--root", str(self.root), "--tool-id", TOOL_ID])
        self.assertEqual(code, 0)
        ready = json.loads(stdout.getvalue())
        self.assertEqual(ready["status"], "ready_metadata_only")

        (self.root / MANIFEST).write_text("{not json", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = DOCTOR.main(["--root", str(self.root), "--tool-id", TOOL_ID])
        self.assertEqual(code, 2)
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["error"]["code"], "invalid_json")
        self.assertFalse(error["network_performed"])
        self.assertFalse(error["write_performed"])

        self._reset_manifest()
        (self.root / "scripts" / "owner_manifest_doctor.py").unlink()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = DOCTOR.main(["--root", str(self.root), "--tool-id", TOOL_ID])
        self.assertEqual(code, 2)
        blocked = json.loads(stdout.getvalue())
        self.assertEqual(blocked["status"], "blocked_contract")
        self.assertIn("doctor-script", blocked["failures"]["contract"])

    def test_03_missing_and_malformed_manifest(self) -> None:
        empty = self.temp / "empty"
        empty.mkdir()
        with self.assertRaises(DOCTOR.DoctorError) as caught:
            DOCTOR.doctor(empty, TOOL_ID)
        self.assertEqual(caught.exception.code, "missing_file")

        (self.root / MANIFEST).write_text("{not json", encoding="utf-8")
        self._assert_doctor_error("invalid_json")

        (self.root / MANIFEST).write_text("[]", encoding="utf-8")
        self._assert_doctor_error("json_object_required")

        (self.root / MANIFEST).write_text('"manifest"', encoding="utf-8")
        self._assert_doctor_error("json_object_required")

    def test_04_empty_all_optional_and_malformed_checklists_rejected(self) -> None:
        def empty_contract(payload: dict) -> None:
            payload["provenance"]["no_write_checks"] = []

        def empty_runtime(payload: dict) -> None:
            payload["provenance"]["runtime_checks"] = []

        def all_optional(payload: dict) -> None:
            for item in payload["provenance"]["runtime_checks"]:
                item["required"] = False

        def duplicate_id(payload: dict) -> None:
            first = payload["provenance"]["no_write_checks"][0]
            second = dict(first)
            payload["provenance"]["runtime_checks"].append(second)

        def missing_id(payload: dict) -> None:
            payload["provenance"]["no_write_checks"][0].pop("id")

        def numeric_path(payload: dict) -> None:
            payload["provenance"]["no_write_checks"][0]["path"] = 5

        def string_required(payload: dict) -> None:
            payload["provenance"]["no_write_checks"][0]["required"] = "yes"

        def numeric_contains(payload: dict) -> None:
            payload["provenance"]["no_write_checks"][0]["contains"] = 7

        def bad_kind(payload: dict) -> None:
            payload["provenance"]["no_write_checks"][0]["kind"] = "symlink"

        def string_item(payload: dict) -> None:
            payload["provenance"]["no_write_checks"][0] = "doctor-script"

        def dict_checklist(payload: dict) -> None:
            payload["provenance"]["no_write_checks"] = {"id": "doctor-script"}

        cases = [
            (empty_contract, "manifest_checklist_empty"),
            (empty_runtime, "manifest_checklist_empty"),
            (all_optional, "manifest_checklist_no_required_file"),
            (duplicate_id, "duplicate_check_id"),
            (missing_id, "manifest_check_id_invalid"),
            (numeric_path, "manifest_check_path_invalid"),
            (string_required, "manifest_check_required_invalid"),
            (numeric_contains, "manifest_check_contains_invalid"),
            (bad_kind, "manifest_check_kind_invalid"),
            (string_item, "manifest_invalid_type"),
            (dict_checklist, "manifest_invalid_type"),
        ]
        for mutate, expected in cases:
            with self.subTest(case=expected):
                self._edit_manifest(mutate)
                self._assert_doctor_error(expected)

    def test_05_invalid_manifest_fields_are_structured_errors(self) -> None:
        cases = [
            (lambda p: p.update(health=[]), "manifest_invalid_type"),
            (lambda p: p.update(provenance=[]), "manifest_invalid_type"),
            (lambda p: p.update(interfaces="cli"), "manifest_invalid_type"),
            (lambda p: p.update(interfaces=[]), "manifest_interfaces_empty"),
            (lambda p: p.update(interfaces=["cli"]), "manifest_invalid_type"),
            (
                lambda p: p["interfaces"][0].pop("id"),
                "manifest_interface_invalid",
            ),
            (
                lambda p: p["interfaces"][0].update(source_path=5),
                "manifest_interface_invalid",
            ),
            (
                lambda p: p.update(notTrustedAsInstruction=False),
                "manifest_trust_boundary_invalid",
            ),
            (
                lambda p: p.update(executionAuthority="execute"),
                "manifest_execution_authority_invalid",
            ),
            (
                lambda p: p["health"].update(proves_current_online=True),
                "manifest_online_claim_invalid",
            ),
            (
                lambda p: p.update(schema_version="agent-tool-manifest.v2"),
                "manifest_schema_mismatch",
            ),
            (lambda p: p.update(id="other-tool"), "manifest_tool_id_mismatch"),
            (lambda p: p.update(manifest_version=0), "manifest_version_invalid"),
            (lambda p: p.update(manifest_version=True), "manifest_version_invalid"),
            (lambda p: p.pop("health"), "manifest_required_field_missing"),
            (
                lambda p: p["provenance"].update(registry_sha256="deadbeef"),
                "volatile_registry_hash_forbidden",
            ),
            (
                lambda p: p["interfaces"][0].update(source_path="C:/private/cli.py"),
                "machine_path_in_interface",
            ),
            (
                lambda p: p["interfaces"][0].update(source_path="/Users/owner/cli.py"),
                "machine_path_in_interface",
            ),
            (
                lambda p: p["provenance"].update(restore_sequence=[1]),
                "manifest_restore_entry_invalid",
            ),
            (
                lambda p: p["provenance"].update(restore_sequence="text"),
                "manifest_invalid_type",
            ),
        ]
        for mutate, expected in cases:
            with self.subTest(case=expected):
                self._edit_manifest(mutate)
                self._assert_doctor_error(expected)

    def test_06_required_file_missing_blocks_but_optional_does_not(self) -> None:
        self._reset_manifest()
        (self.root / "scripts" / "owner_manifest_doctor.py").unlink()
        blocked = DOCTOR.doctor(self.root, TOOL_ID)
        self.assertEqual(blocked["status"], "blocked_contract")
        self.assertFalse(blocked["truth"]["contract_ready"]["value"])
        self.assertFalse(blocked["truth"]["runtime_ready"]["value"])
        self.assertIn("doctor-script", blocked["failures"]["contract"])

        shutil.copy2(
            ROOT / "scripts" / "owner_manifest_doctor.py",
            self.root / "scripts" / "owner_manifest_doctor.py",
        )
        (self.root / "src" / "question_research_poc" / "__init__.py").unlink()
        blocked = DOCTOR.doctor(self.root, TOOL_ID)
        self.assertEqual(blocked["status"], "blocked_runtime")
        self.assertTrue(blocked["truth"]["contract_ready"]["value"])
        self.assertFalse(blocked["truth"]["runtime_ready"]["value"])
        self.assertIn("package-init", blocked["failures"]["runtime"])

        shutil.copy2(
            ROOT / "src" / "question_research_poc" / "__init__.py",
            self.root / "src" / "question_research_poc" / "__init__.py",
        )
        (self.root / "README.md").unlink()
        optional = DOCTOR.doctor(self.root, TOOL_ID)
        self.assertEqual(optional["status"], "ready_metadata_only")
        self.assertTrue(optional["truth"]["contract_ready"]["value"])
        self.assertTrue(optional["truth"]["runtime_ready"]["value"])
        self.assertEqual(optional["failures"], {"contract": [], "runtime": []})
        readme = {
            item["id"]: item for item in optional["checks"]["contract"]
        }["readme-discoverability"]
        self.assertFalse(readme["required"])
        self.assertEqual(readme["status"], "missing_or_mismatch")

    def test_07_absolute_and_escape_paths_are_rejected(self) -> None:
        with self.assertRaises(DOCTOR.DoctorError) as caught:
            DOCTOR.resolve_inside(self.root, "../escape")
        self.assertEqual(caught.exception.code, "path_escape")

        outside = str(Path(self.temp) / "outside.txt")
        with self.assertRaises(DOCTOR.DoctorError) as caught:
            DOCTOR.resolve_inside(self.root, outside)
        self.assertEqual(caught.exception.code, "absolute_path_forbidden")

        self._edit_manifest(
            lambda p: p["provenance"]["no_write_checks"][0].update(
                path="../outside.txt"
            )
        )
        self._assert_doctor_error("path_escape")

        self._edit_manifest(
            lambda p: p["provenance"]["no_write_checks"][0].update(path=outside)
        )
        self._assert_doctor_error("absolute_path_forbidden")

    def test_08_symlink_escape_is_rejected_or_explicitly_skipped(self) -> None:
        if os.environ.get("TEST_SYMLINK_KNOWN_UNAVAILABLE") == "1":
            self.skipTest(
                "symlink creation known unavailable on this host "
                "(WinError 1314 observed in round 1); not retried"
            )
        outside_directory = self.temp / "outside"
        outside_directory.mkdir()
        outside_file = outside_directory / "secret.txt"
        outside_file.write_text("outside", encoding="utf-8")
        link = self.root / "linked.txt"
        try:
            os.symlink(outside_file, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink privilege unavailable: {exc}")
        self._edit_manifest(
            lambda p: p["provenance"]["no_write_checks"][0].update(path="linked.txt")
        )
        self._assert_doctor_error("path_escape")

    def test_09_current_receipt_is_qualified_untrusted_and_does_not_write(
        self,
    ) -> None:
        receipt = self._write_receipt(self.temp / "receipts" / "current")
        before = self._snapshot()
        result = DOCTOR.doctor(self.root, TOOL_ID, receipt)
        after = self._snapshot()
        self.assertEqual(before, after)
        fresh = result["truth"]["fresh_e2e_pass"]
        self.assertTrue(fresh["value"])
        self.assertEqual(fresh["status"], "passed_current")
        self.assertEqual(fresh["reason_codes"], [])
        self.assertFalse(fresh["checked_at_naive_utc_assumed"])
        self.assertFalse(fresh["future_timestamp"])
        self.assertTrue(fresh["artifact_hash_matches"])
        self.assertEqual(
            fresh["qualification"]["kind"], "caller_declared_synthetic_receipt"
        )
        self.assertFalse(fresh["qualification"]["trusted_as_instruction"])
        self.assertEqual(
            fresh["qualification"]["proves"],
            "artifact_sha256_and_time_window_only",
        )
        self.assertIn(
            "owner_earned_execution", fresh["qualification"]["does_not_prove"]
        )
        self.assertFalse(result["publish_authorized"])
        self.assertFalse(result["permissions_granted"])
        self.assertFalse(result["evidence_qualification"]["runtime_executed"])
        self.assertFalse(
            result["evidence_qualification"][
                "receipt_can_grant_publish_or_permissions"
            ]
        )
        self.assertEqual(result["status"], "ready_metadata_only")
        # A small positive clock skew inside the documented tolerance is fresh.
        near_future = self._write_receipt(
            self.temp / "receipts" / "near-future",
            checked_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        )
        self.assertTrue(self._fresh(near_future)["value"])

    def test_10_future_and_naive_timestamp_rules(self) -> None:
        future = self._write_receipt(
            self.temp / "receipts" / "future",
            checked_at=(datetime.now(timezone.utc) + timedelta(days=3650)).isoformat(),
        )
        fresh = self._fresh(future)
        self.assertFalse(fresh["value"])
        self.assertIn("receipt_future_timestamp", fresh["reason_codes"])

        naive_future = self._write_receipt(
            self.temp / "receipts" / "naive-future",
            checked_at=(
                datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(days=3650)
            ).isoformat(),
        )
        fresh = self._fresh(naive_future)
        self.assertFalse(fresh["value"])
        self.assertIn("receipt_future_timestamp", fresh["reason_codes"])

        naive_current = self._write_receipt(
            self.temp / "receipts" / "naive-current",
            checked_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )
        fresh = self._fresh(naive_current)
        self.assertTrue(fresh["value"])
        self.assertTrue(fresh["checked_at_naive_utc_assumed"])

        naive_stale = self._write_receipt(
            self.temp / "receipts" / "naive-stale",
            checked_at=(
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(hours=200)
            ).isoformat(),
        )
        self.assertIn("receipt_stale", self._fresh(naive_stale)["reason_codes"])

        invalid = self._write_receipt(
            self.temp / "receipts" / "invalid-time", checked_at="not-a-timestamp"
        )
        self.assertIn(
            "receipt_checked_at_invalid", self._fresh(invalid)["reason_codes"]
        )

        payload = json.loads(invalid.read_text(encoding="utf-8"))
        payload.pop("checked_at")
        invalid.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn(
            "receipt_checked_at_invalid", self._fresh(invalid)["reason_codes"]
        )

    def test_11_stale_receipt_and_ttl_window(self) -> None:
        stale = self._write_receipt(
            self.temp / "receipts" / "stale",
            checked_at=(datetime.now(timezone.utc) - timedelta(hours=169)).isoformat(),
        )
        self.assertIn("receipt_stale", self._fresh(stale)["reason_codes"])

        short_ttl = self._write_receipt(
            self.temp / "receipts" / "short-ttl",
            checked_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        )
        fresh = DOCTOR.doctor(
            self.root, TOOL_ID, short_ttl, ttl_hours=1
        )["truth"]["fresh_e2e_pass"]
        self.assertFalse(fresh["value"])
        self.assertIn("receipt_stale", fresh["reason_codes"])
        self.assertEqual(fresh["ttl_hours"], 1)

    def test_12_artifact_hash_drift_missing_and_escape_fail_closed(self) -> None:
        drifted = self._write_receipt(self.temp / "receipts" / "drift")
        (drifted.parent / "synthetic-result.json").write_text(
            "drift", encoding="utf-8"
        )
        self.assertIn("artifact_hash_drift", self._fresh(drifted)["reason_codes"])

        missing = self._write_receipt(
            self.temp / "receipts" / "missing", artifact_path="missing.json"
        )
        self.assertIn("receipt_artifact_missing", self._fresh(missing)["reason_codes"])

        malformed = self._write_receipt(
            self.temp / "receipts" / "malformed-hash", artifact_sha256="zz"
        )
        self.assertIn(
            "receipt_artifact_hash_invalid", self._fresh(malformed)["reason_codes"]
        )

        escape = self._write_receipt(
            self.temp / "receipts" / "escape", artifact_path="../outside.json"
        )
        self.assertIn("path_escape", self._fresh(escape)["reason_codes"])

        absolute = self._write_receipt(
            self.temp / "receipts" / "absolute",
            artifact_path=str(Path(self.temp) / "outside.json"),
        )
        self.assertIn("absolute_path_forbidden", self._fresh(absolute)["reason_codes"])

    def test_13_corrupt_receipt_and_artifact_contract(self) -> None:
        corrupt_dir = self.temp / "receipts" / "corrupt"
        corrupt_dir.mkdir(parents=True)
        corrupt = corrupt_dir / "receipt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        self.assertIn("invalid_json", self._fresh(corrupt)["reason_codes"])

        list_receipt = corrupt_dir / "list-receipt.json"
        list_receipt.write_text("[]", encoding="utf-8")
        self.assertIn("json_object_required", self._fresh(list_receipt)["reason_codes"])

        no_artifact = self._write_receipt(self.temp / "receipts" / "no-artifact")
        payload = json.loads(no_artifact.read_text(encoding="utf-8"))
        payload["artifact"] = "artifact"
        no_artifact.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("receipt_artifact_invalid", self._fresh(no_artifact)["reason_codes"])

        numeric_path = self._write_receipt(self.temp / "receipts" / "numeric-path")
        payload = json.loads(numeric_path.read_text(encoding="utf-8"))
        payload["artifact"]["path"] = 7
        numeric_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("receipt_artifact_invalid", self._fresh(numeric_path)["reason_codes"])

    def test_14_wrong_tool_schema_status_and_truth_are_rejected(self) -> None:
        wrong_tool = self._write_receipt(
            self.temp / "receipts" / "wrong-tool", tool_id="another-tool"
        )
        self.assertIn(
            "receipt_tool_id_mismatch", self._fresh(wrong_tool)["reason_codes"]
        )

        wrong_schema = self._write_receipt(
            self.temp / "receipts" / "wrong-schema",
            schema_version="agent-tool-owner-synthetic-receipt.v2",
        )
        self.assertIn(
            "receipt_schema_mismatch", self._fresh(wrong_schema)["reason_codes"]
        )

        wrong_status = self._write_receipt(
            self.temp / "receipts" / "wrong-status", status="failed"
        )
        self.assertIn(
            "receipt_status_invalid", self._fresh(wrong_status)["reason_codes"]
        )

        real_usage = self._write_receipt(
            self.temp / "receipts" / "real-usage",
            truth={
                "fresh_e2e_pass": True,
                "real_usage_proof": True,
                "current_online": False,
            },
        )
        self.assertIn(
            "receipt_real_usage_claim_invalid",
            self._fresh(real_usage)["reason_codes"],
        )

        online = self._write_receipt(
            self.temp / "receipts" / "online",
            truth={
                "fresh_e2e_pass": True,
                "real_usage_proof": False,
                "current_online": True,
            },
        )
        self.assertIn(
            "receipt_online_claim_invalid", self._fresh(online)["reason_codes"]
        )

        not_fresh = self._write_receipt(
            self.temp / "receipts" / "not-fresh",
            truth={
                "fresh_e2e_pass": False,
                "real_usage_proof": False,
                "current_online": False,
            },
        )
        self.assertIn(
            "receipt_truth_invalid", self._fresh(not_fresh)["reason_codes"]
        )

        truth_list = self._write_receipt(
            self.temp / "receipts" / "truth-list", truth=[]
        )
        self.assertIn(
            "receipt_truth_invalid", self._fresh(truth_list)["reason_codes"]
        )

    def test_15_invalid_ttl_is_structured_or_cli_exit_two(self) -> None:
        self.assertEqual(
            DOCTOR.doctor(self.root, TOOL_ID, ttl_hours=1)["truth"][
                "fresh_e2e_pass"
            ]["ttl_hours"],
            1,
        )
        # No arbitrary upper bound is imposed: a long TTL is the caller's own
        # window choice, not an invalid type.
        self.assertEqual(
            DOCTOR.doctor(self.root, TOOL_ID, ttl_hours=87600)["truth"][
                "fresh_e2e_pass"
            ]["ttl_hours"],
            87600,
        )
        for value, code in (
            (0, "invalid_ttl_nonpositive"),
            (-5, "invalid_ttl_nonpositive"),
            (True, "invalid_ttl"),
            ("168", "invalid_ttl"),
            (1.5, "invalid_ttl"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(DOCTOR.DoctorError) as caught:
                    DOCTOR.doctor(self.root, TOOL_ID, ttl_hours=value)
                self.assertEqual(caught.exception.code, code)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = DOCTOR.main(
                ["--root", str(self.root), "--tool-id", TOOL_ID, "--ttl-hours", "0"]
            )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stderr.getvalue())["error"]["code"],
            "invalid_ttl_nonpositive",
        )

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                DOCTOR.main(
                    [
                        "--root",
                        str(self.root),
                        "--tool-id",
                        TOOL_ID,
                        "--ttl-hours",
                        "not-a-number",
                    ]
                )
        self.assertEqual(caught.exception.code, 2)

    def test_16_public_manifest_static_contract_is_metadata_only(self) -> None:
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "agent-tool-manifest.v1")
        self.assertEqual(manifest["id"], TOOL_ID)
        self.assertIs(manifest["notTrustedAsInstruction"], True)
        self.assertEqual(manifest["executionAuthority"], "none_metadata_only")
        self.assertIs(manifest["health"]["proves_current_online"], False)
        self.assertNotIn("registry_sha256", manifest["provenance"])
        seen: set[str] = set()
        for group in ("no_write_checks", "runtime_checks"):
            items = manifest["provenance"][group]
            self.assertTrue(items)
            self.assertTrue(
                any(item["required"] and item["kind"] == "file" for item in items)
            )
            for item in items:
                relative = Path(item["path"])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertEqual(item["kind"], "file")
                self.assertIn(item["required"], (True, False))
                self.assertNotIn(item["id"], seen)
                seen.add(item["id"])
                self.assertTrue((ROOT / relative).is_file())
                self.assertNotEqual(relative.parts[0], "config")
        self.assertTrue(
            any(
                item["path"] == "src/question_research_poc/cli.py"
                for item in manifest["provenance"]["runtime_checks"]
            )
        )
        self.assertTrue(
            all(
                isinstance(entry, str) and entry.strip()
                for entry in manifest["provenance"]["restore_sequence"]
            )
        )
        self.assertIsNone(
            DOCTOR._MACHINE_PATH.search(json.dumps(manifest["interfaces"]))
        )

        result = DOCTOR.doctor(ROOT, TOOL_ID)
        self.assertEqual(
            result["manifest"]["sha256"], DOCTOR.sha256_file(ROOT / MANIFEST)
        )
        self.assertEqual(
            result["runtime_checks_semantics"],
            "static_file_presence_only_not_execution",
        )
        self.assertFalse(result["evidence_qualification"]["network_performed"])
        self.assertFalse(result["evidence_qualification"]["write_performed"])

    def test_17_check_ids_are_unique_after_normalization_across_lists(self) -> None:
        # Exact duplicate id across the contract and runtime lists fails closed.
        self._edit_manifest(
            lambda p: p["provenance"]["runtime_checks"][0].update(
                id=p["provenance"]["no_write_checks"][0]["id"]
            )
        )
        self._assert_doctor_error("duplicate_check_id")

        # A whitespace-padded variant is not silently collapsed into the same
        # identity: the manifest is rejected instead.
        self._edit_manifest(
            lambda p: p["provenance"]["runtime_checks"][0].update(
                id=" " + p["provenance"]["no_write_checks"][0]["id"] + " "
            )
        )
        self._assert_doctor_error("manifest_check_id_whitespace")

        # A duplicate inside the same list also fails closed.
        self._edit_manifest(
            lambda p: p["provenance"]["no_write_checks"][1].update(
                id=p["provenance"]["no_write_checks"][0]["id"]
            )
        )
        self._assert_doctor_error("duplicate_check_id")

        # An accepted manifest emits unique, nonempty, already-stripped ids only.
        self._reset_manifest()
        result = DOCTOR.doctor(self.root, TOOL_ID)
        emitted = [
            item["id"]
            for group in ("contract", "runtime")
            for item in result["checks"][group]
        ]
        self.assertEqual(len(emitted), len(set(emitted)))
        self.assertTrue(all(item == item.strip() and item for item in emitted))
        self.assertEqual(
            len(emitted),
            len(self._manifest()["provenance"]["no_write_checks"])
            + len(self._manifest()["provenance"]["runtime_checks"]),
        )

    def test_18_invalid_utf8_json_is_structured_not_success(self) -> None:
        (self.root / MANIFEST).write_bytes(b"\xff")
        with self.assertRaises(DOCTOR.DoctorError) as caught:
            DOCTOR.doctor(self.root, TOOL_ID)
        self.assertEqual(caught.exception.code, "invalid_encoding")

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = DOCTOR.main(["--root", str(self.root), "--tool-id", TOOL_ID])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["status"], "blocked")
        self.assertEqual(error["error"]["code"], "invalid_encoding")
        self.assertFalse(error["network_performed"])
        self.assertFalse(error["write_performed"])

        # Restore a valid manifest, then confirm a bad-encoding receipt is a
        # rejected receipt rather than an unhandled crash.
        self._reset_manifest()
        receipt_dir = self.temp / "receipts" / "bad-encoding"
        receipt_dir.mkdir(parents=True)
        receipt = receipt_dir / "receipt.json"
        receipt.write_bytes(b"\xff")
        self.assertIn("invalid_encoding", self._fresh(receipt)["reason_codes"])

        # Real file-error boundaries stay distinct from encoding errors.
        with self.assertRaises(DOCTOR.DoctorError) as missing:
            DOCTOR.read_json(self.temp / "does-not-exist.json")
        self.assertEqual(missing.exception.code, "missing_file")

    def test_19_restore_sequence_is_data_only_and_never_executed(self) -> None:
        probe = "owner-manifest-doctor-probe.txt"
        entry = f"echo example.invalid > {probe}"
        note = "Plain descriptive recovery note."

        self._edit_manifest(
            lambda p: p["provenance"].update(restore_sequence=[entry, note])
        )
        before = self._snapshot()
        result = DOCTOR.doctor(self.root, TOOL_ID)
        after = self._snapshot()
        self.assertEqual(before, after)
        self.assertEqual(result["recovery"], [entry, note])
        self.assertFalse(result["metadata_authorizes_execution"])
        self.assertFalse(result["write_performed"])
        self.assertFalse(any(path.name == probe for path in self.root.rglob("*")))

        # The doctor source has no execution primitive to run the data with.
        source = SCRIPT.read_text(encoding="utf-8")
        for primitive in ("subprocess", "os.system", "eval(", "exec(", "popen"):
            self.assertNotIn(primitive, source)


if __name__ == "__main__":
    unittest.main()
