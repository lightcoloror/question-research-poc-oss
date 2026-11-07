from __future__ import annotations

import json
import shutil
from pathlib import Path

from question_research_poc.cli import main as cli_main
from question_research_poc.mcp_server import call_mcp_tool, list_mcp_tools
from question_research_poc.research_output import (
    RESEARCH_OUTPUT_SCHEMA,
    build_research_output,
    export_research_output,
    research_output_schema_path,
    validate_research_output,
)
from question_research_poc.storage import read_jsonl, rewrite_jsonl


FIXTURES = Path(__file__).parent / "fixtures" / "research-output-v1"
VERIFIED_PROJECT = FIXTURES / "verified-project"
CANONICAL_ARTIFACT = FIXTURES / "canonical" / "research-output.v1.json"
CANONICAL_ARTIFACT_SHA256 = "27ae62971f6754009859be87f07a47d9673484c5dea32db0f48e13ce0779a97c"
CANONICAL_PAYLOAD_SHA256 = "89eb27ba1cafb9b39f974209bc0756934d620ee3bf7028476ad776306bb66a2f"


def _copy_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(VERIFIED_PROJECT, project)
    return project


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_fixture_exports_schema_valid_guarded_artifact(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)

    receipt = export_research_output(
        project,
        scope="Offline canonical contract verification.",
        audience="content-creation-system",
        requested_outputs=["article", "content-video-brief.v1"],
        scope_constraints=["synthetic-only", "no-external-api"],
    )
    artifact = _payload(Path(receipt["artifact_path"]))

    assert receipt["ok"] is True
    assert receipt["validation"]["status"] == "pass"
    assert artifact["schema"] == RESEARCH_OUTPUT_SCHEMA
    assert artifact["schema_version"] == "1.0.0"
    assert artifact["audience"] == "content-creation-system"
    assert artifact["requested_outputs"] == ["article", "content-video-brief.v1"]
    assert artifact["guarded_final_answer"]["status"] == "verified"
    assert artifact["guarded_final_answer"]["ready"] is True
    assert artifact["guarded_final_answer"]["claim_ids"] == ["claim_fixture_contract"]
    assert artifact["guarded_final_answer"]["evidence_ids"] == ["evidence_fixture_support"]
    assert {item["source_id"] for item in artifact["sources"]} == {"source_fixture_primary", "source_fixture_video"}
    assert all(item["hash"]["status"] == "verified" for item in artifact["sources"])
    assert all(item["ref_status"] == "resolved" for item in artifact["sources"])
    assert artifact["contradictions"] == [
        {
            "claim_id": "claim_fixture_contract",
            "evidence_id": "evidence_fixture_rejected_contradiction",
            "source_id": "source_fixture_primary",
            "evidence_status": "rejected",
            "resolution_status": "rejected",
        }
    ]
    assert artifact["media_refs"][0]["source_id"] == "source_fixture_video"
    assert any(item["source_id"] == "source_fixture_video" for item in artifact["visual_leads"])
    assert len(artifact["quotable_facts"]) == 1
    assert artifact["quotable_facts"][0]["word_count"] <= 25
    assert len(artifact["quotable_facts"][0]["text"]) <= 120
    assert artifact["provenance"]["offline_only"] is True
    assert artifact["provenance"]["external_api_called"] is False
    assert artifact["provenance"]["model_memory_used_as_evidence"] is False
    assert validate_research_output(artifact)["ok"] is True
    assert research_output_schema_path().is_file()


def test_same_project_and_options_are_byte_stable(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    target = tmp_path / "research-output.v1.json"
    kwargs = {
        "scope": "Stable export.",
        "audience": "content-creation-system",
        "requested_outputs": ["article"],
    }

    first = export_research_output(project, target, **kwargs)
    first_bytes = target.read_bytes()
    second = export_research_output(project, target, **kwargs)

    assert target.read_bytes() == first_bytes
    assert first["artifact_sha256"] == second["artifact_sha256"]
    assert first["payload_sha256"] == second["payload_sha256"]


def test_checked_in_canonical_artifact_matches_fresh_export(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    target = tmp_path / "research-output.v1.json"

    receipt = export_research_output(
        project,
        target,
        scope="Offline canonical contract verification.",
        audience="content-creation-system",
        requested_outputs=["article", "content-video-brief.v1"],
        scope_constraints=["synthetic-only", "no-external-api"],
    )

    assert target.read_bytes() == CANONICAL_ARTIFACT.read_bytes()
    assert receipt["artifact_sha256"] == CANONICAL_ARTIFACT_SHA256
    assert receipt["payload_sha256"] == CANONICAL_PAYLOAD_SHA256


def test_negative_fixtures_fail_closed(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "negative-cases.json").read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        project = _copy_project(tmp_path / case["id"])
        evidence_path = project / "evidence.jsonl"
        rows = read_jsonl(evidence_path)
        for row in rows:
            if row["id"] == case["target"]:
                row.update(case["changes"])
        rewrite_jsonl(evidence_path, rows)

        payload = build_research_output(project)

        assert case["expected_blocker"] in payload["completeness"]["blocking_gates"]
        assert payload["guarded_final_answer"]["status"] == "blocked"
        assert payload["guarded_final_answer"]["answer"] is None
        assert validate_research_output(payload)["ok"] is True


def test_local_archive_hash_drift_blocks_guarded_answer(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    archive = project / "archive" / "primary-source.md"
    archive.write_text(archive.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")

    payload = build_research_output(project)

    assert "source_hash_mismatch" in payload["completeness"]["blocking_gates"]
    assert payload["guarded_final_answer"]["status"] == "blocked"
    assert next(item for item in payload["sources"] if item["source_id"] == "source_fixture_primary")["hash"]["status"] == "mismatch"


def test_cli_and_mcp_export_the_same_contract(tmp_path: Path, capsys) -> None:
    cli_project = _copy_project(tmp_path / "cli")
    cli_target = tmp_path / "cli-output.json"

    assert cli_main(
        [
            "export-research-output",
            "--project",
            str(cli_project),
            "--output",
            str(cli_target),
            "--scope",
            "Consumer handoff.",
            "--audience",
            "content-creation-system",
            "--requested-output",
            "article",
        ]
    ) == 0
    cli_receipt = json.loads(capsys.readouterr().out)

    assert cli_receipt["ok"] is True
    assert _payload(cli_target)["schema"] == RESEARCH_OUTPUT_SCHEMA
    assert "export_research_output" in {item["name"] for item in list_mcp_tools()}

    mcp_project = _copy_project(tmp_path / "mcp")
    mcp_target = tmp_path / "mcp-output.json"
    mcp_receipt = call_mcp_tool(
        "export_research_output",
        {
            "root": str(mcp_project),
            "output_path": str(mcp_target),
            "scope": "Consumer handoff.",
            "audience": "content-creation-system",
            "requested_outputs": ["article"],
        },
    )

    assert mcp_receipt["ok"] is True
    assert _payload(mcp_target)["schema"] == RESEARCH_OUTPUT_SCHEMA
