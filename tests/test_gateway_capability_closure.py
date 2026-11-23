from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from question_research_poc import gateway_capability_closure as closure_module
from question_research_poc.cli import build_parser
from question_research_poc.gateway_capability_closure import (
    run_gateway_capability_closure,
    validate_closure_run,
)
from research_workflow import model_gateway as arw_model_gateway


requires_semantic_arw = pytest.mark.skipif(
    not (
        hasattr(arw_model_gateway, "ModelGatewaySemanticIncompatible")
        and "visual_claim_assist" in getattr(arw_model_gateway, "SUPPORTED_TASKS", set())
    ),
    reason="published ARW install snapshot does not yet expose the semantic vision contract",
)


def _canonical_schema() -> Path:
    configured = os.environ.get("CLOSURE_RUN_V1_SCHEMA")
    candidates = [
        Path(configured) if configured else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    pytest.skip("canonical closure-run.v1 schema is not available")


def _authority_inputs(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in ("source_inventory", "owner_routing", "tool_registry"):
        path = root / f"{name}.json"
        path.write_text(
            json.dumps({"schema": f"synthetic-{name}.v1", "execution_authorized": False}),
            encoding="utf-8",
        )
        result[name] = path
    return result


def _run(root: Path, run_id: str, *, resume: bool = False) -> dict:
    authority = _authority_inputs(root / "authority-source")
    return run_gateway_capability_closure(
        output_root=root / "runs",
        closure_run_id=run_id,
        closure_schema_path=_canonical_schema(),
        source_inventory_path=authority["source_inventory"],
        owner_routing_path=authority["owner_routing"],
        tool_registry_path=authority["tool_registry"],
        resume=resume,
    )


def test_closure_represents_unavailable_arw_as_fresh_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_model_assist(*_args: object, **_kwargs: object) -> dict:
        return {
            "schema": "question_research_poc.model_assist_bridge_status.v1",
            "ok": False,
            "status": "blocked",
            "error_class": "arw_consumer_unavailable",
            "candidate_refs": [],
            "execution_performed": False,
            "provider_called": False,
            "external_io_performed": False,
            "model_output_status": "unavailable",
            "research_truth_effect": "none",
            "evidence_status_change": "none",
            "automatic_fallback_allowed": False,
            "automatic_retry_allowed": False,
        }

    monkeypatch.setattr(closure_module, "run_gateway_model_assist", unavailable_model_assist)
    result = _run(tmp_path, "qrp-arw-capability-unavailable")
    closure = json.loads(Path(result["closure_run_path"]).read_text(encoding="utf-8"))
    matrix = json.loads(Path(result["capability_matrix_path"]).read_text(encoding="utf-8"))

    assert result["status"] == "completed"
    assert result["failure_point"] == "text_runtime_gate"
    assert closure["truth"]["contract_ready"]["value"] is True
    assert closure["truth"]["runtime_ready"]["value"] is False
    assert closure["truth"]["fresh_e2e_pass"]["value"] is False
    assert closure["truth"]["real_usage_proof"]["value"] is False
    assert closure["truth"]["current_online"]["value"] is False
    assert matrix["capabilities"]["text"]["fresh_e2e_pass"] is False
    assert matrix["capabilities"]["vision"]["fresh_e2e_pass"] is False
    assert matrix["capabilities"]["embedding"]["fresh_e2e_pass"] is False


@requires_semantic_arw
def test_synthetic_capability_closure_is_idempotent_and_truthful(tmp_path: Path) -> None:
    first = _run(tmp_path, "qrp-arw-capability-fixture")
    closure_path = Path(first["closure_run_path"])
    first_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()
    second = _run(tmp_path, "qrp-arw-capability-fixture")

    assert first["status"] == "completed"
    assert first["idempotent_reuse"] is False
    assert second["idempotent_reuse"] is True
    assert hashlib.sha256(closure_path.read_bytes()).hexdigest() == first_hash
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    assert [stage["status"] for stage in closure["stages"]] == ["passed", "failed", "resumed"]
    assert closure["stages"][1]["failure_point"] == "embedding_runtime_gate"
    assert closure["truth"]["contract_ready"]["value"] is True
    assert closure["truth"]["runtime_ready"]["value"] is False
    assert closure["truth"]["fresh_e2e_pass"]["value"] is False
    assert closure["truth"]["real_usage_proof"]["value"] is False
    assert closure["truth"]["current_online"]["value"] is False
    assert closure["truth"]["verified_available"] is False
    assert closure["execution_authorized"] is False
    matrix = json.loads(Path(first["capability_matrix_path"]).read_text(encoding="utf-8"))
    assert matrix["capabilities"]["text"]["fresh_e2e_pass"] is True
    assert matrix["capabilities"]["vision"]["fresh_e2e_pass"] is True
    assert matrix["capabilities"]["embedding"]["fresh_e2e_pass"] is False
    assert matrix["capabilities"]["embedding"]["fresh_fail_closed_probe_pass"] is True
    assert matrix["capabilities"]["embedding"]["runtime_status"] == "blocked_runtime_missing"
    assert matrix["invariants"]["service_9082"] == "stopped_by_design"


@requires_semantic_arw
def test_closure_resume_rebuilds_only_the_missing_final_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _run(tmp_path, "qrp-arw-capability-resume")
    closure_path = Path(first["closure_run_path"])
    expected = closure_path.read_bytes()
    receipt_dir = closure_path.parent / "synthetic-project" / "model-assist-receipts"
    receipt_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in receipt_dir.glob("closure-*.json")
    }
    assert set(receipt_hashes) == {"closure-text.json", "closure-vision.json"}
    closure_path.unlink()

    def unexpected_mock_server(*args: object, **kwargs: object) -> None:
        raise AssertionError("resume must reuse receipts without starting the loopback provider")

    import model_provider_gateway.mock_server as mock_server_module

    monkeypatch.setattr(mock_server_module, "mock_server", unexpected_mock_server)

    resumed = _run(tmp_path, "qrp-arw-capability-resume", resume=True)

    assert resumed["resumed"] is True
    assert closure_path.read_bytes() == expected
    assert resumed["failure_point"] == "embedding_runtime_gate"
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in receipt_dir.glob("closure-*.json")
    } == receipt_hashes


@requires_semantic_arw
def test_closure_semantics_fail_closed_on_online_claim_and_hash_drift(tmp_path: Path) -> None:
    result = _run(tmp_path, "qrp-arw-capability-negative")
    run_dir = Path(result["closure_run_path"]).parent
    closure = json.loads(Path(result["closure_run_path"]).read_text(encoding="utf-8"))
    schema = _canonical_schema()
    online = copy.deepcopy(closure)
    online["truth"]["current_online"]["value"] = True

    with pytest.raises(ValueError, match="current_online"):
        validate_closure_run(online, run_dir=run_dir, schema_path=schema)

    stage_path = run_dir / closure["stages"][0]["receipt_ref"]["path"]
    stage_path.write_bytes(stage_path.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="hash drift"):
        validate_closure_run(closure, run_dir=run_dir, schema_path=schema)


def test_cli_exposes_one_stable_closure_command(tmp_path: Path) -> None:
    authority = _authority_inputs(tmp_path)
    args = build_parser().parse_args(
        [
            "gateway-capability-closure",
            "--output-root",
            str(tmp_path / "runs"),
            "--closure-run-id",
            "stable-command-fixture",
            "--closure-schema",
            str(_canonical_schema()),
            "--source-inventory",
            str(authority["source_inventory"]),
            "--owner-routing",
            str(authority["owner_routing"]),
            "--tool-registry",
            str(authority["tool_registry"]),
            "--resume",
        ]
    )
    assert args.command == "gateway-capability-closure"
    assert args.resume is True
