from __future__ import annotations

import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from question_research_poc.cli import main as cli_main
from question_research_poc.ai_research_bridge import import_ai_research_result, plan_ai_research_search, resolve_ai_research_url, run_ai_research_agent_research, run_ai_research_search
from question_research_poc.agent_interface import get_gate_details, get_project_dashboard, get_project_overview, get_project_status, get_review_queue, get_tool_health_dashboard, read_workflow_artifact, run_next_step
from question_research_poc.agent_manifest import build_agent_manifest
from question_research_poc.agent_runbook import build_agent_runbook
from question_research_poc.bridge_actions import enqueue_bridge_actions, plan_bridge_action, run_bridge_action
from question_research_poc.bridge_runs import create_bridge_run, list_bridge_runs, read_bridge_run, retry_bridge_run_plan
from question_research_poc.cockpit_readiness import audit_cockpit_readiness
from question_research_poc.completeness_audit import audit_research_completeness
from question_research_poc.demo_project import build_demo_project
from question_research_poc.external_researcher_bridge import answer_external_researcher_followup, check_external_researcher_automation_profiles, export_external_researcher_bundle, import_external_researcher_report, list_external_researcher_reports, plan_external_researcher_automation, plan_external_researcher_session, prepare_external_researcher_login_profiles, run_external_researcher_automation, save_external_researcher_report_draft, write_external_researcher_profile_template
from question_research_poc.final_answer import export_final_answer
from question_research_poc.graph_candidates import export_reviewed_graph, generate_graph_candidates, list_graph_candidates, review_graph_candidate
from question_research_poc.guarded_e2e_fixture import FIXTURE_STATE_FILE, FIXTURE_STATE_JSON_SCHEMA, FIXTURE_STATE_SCHEMA_VERSION, run_guarded_e2e_fixture
from question_research_poc.mcp_server import call_mcp_tool, list_mcp_tools
from question_research_poc.omnigent_poc import run_omnigent_external_research_poc
from question_research_poc.orchestrator import add_claim, add_evidence, add_source, add_video, draft_answer, init_project, list_records, review_evidence, review_source
from question_research_poc.models import project_paths
from question_research_poc.research_plan import build_research_plan, read_research_plan
from question_research_poc.research_gaps import analyze_research_gaps, plan_followup_queries
from question_research_poc.research_loop import export_research_loop_review_pack, list_research_loops, read_research_loop, run_research_loop
from question_research_poc.research_pack import create_logseq_review_handoff, export_research_pack, export_research_pack_to_obsidian
from question_research_poc.project_overview import build_project_overview
from question_research_poc.research_stage import classify_research_stage
from question_research_poc.review_state import build_review_queue, build_workflow_payload
from question_research_poc.runtime_config import RUNTIME_CONFIG_PATH, default_project_root, load_runtime_config, web_host, web_port, web_url
from question_research_poc.video_artifact_import import import_video_knowledge_artifacts
from question_research_poc.video_knowledge_bridge import _parse_json, check_video_run_artifacts, plan_video_knowledge_run
from question_research_poc.web_fetch_bridge import fetch_source_content, plan_fetch_source_content
from question_research_poc.tool_bridge_status import build_tool_bridge_status
from question_research_poc.tool_executor import run_local_tool_action
from question_research_poc.vane_perplexica_bridge import import_vane_perplexica_result, plan_vane_perplexica_search
from question_research_poc.source_inbox import add_inbox_item, import_inbox_item_as_source, list_inbox_items, reject_inbox_item
from question_research_poc.sync_safety import audit_sync_safety
from question_research_poc import storage as storage_module
from question_research_poc.storage import rewrite_jsonl
from question_research_poc.work_queue import enqueue_runbook_tasks, enqueue_task, list_tasks, run_work_queue_item, update_task_status
from question_research_poc.web_app import _project_payload, _tools_payload
from question_research_poc.workflow_engine import audit_research_gates, route_research_task, run_multi_perspective_review, run_reader_persona_review, run_workflow_engine


def test_research_core_flow(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "如何做问题导向研究？")
    source = add_source(project, title="本地笔记", path="notes.md", quality="good")
    claim = add_claim(project, text="研究流程需要证据和审核")
    evidence = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="来源记录了审核步骤", relation="supports")
    review_evidence(project, evidence_id=evidence.id, status="verified", confidence="high")

    assert len(list_records(project, "sources")) == 1
    assert "研究流程需要证据和审核" in draft_answer(project)


def test_concurrent_evidence_writes_preserve_jsonl_records(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "并发写入证据会不会丢记录？")
    source = add_source(project, title="来源", url="https://example.com", quality="good")
    claim = add_claim(project, text="并发写入需要文件锁")
    existing = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="预置证据")

    def add_row(index: int) -> str:
        return add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note=f"并发证据 {index}").id

    def review_existing(index: int) -> str:
        review_evidence(project, evidence_id=existing.id, status="verified", confidence="high", notes=f"review {index}")
        return existing.id

    with ThreadPoolExecutor(max_workers=12) as executor:
        add_futures = [executor.submit(add_row, index) for index in range(30)]
        review_futures = [executor.submit(review_existing, index) for index in range(30)]
        added_ids = [future.result() for future in add_futures]
        [future.result() for future in review_futures]

    evidence = list_records(project, "evidence")
    evidence_ids = {row["id"] for row in evidence}
    assert len(evidence) == 31
    assert set(added_ids).issubset(evidence_ids)
    assert existing.id in evidence_ids
    existing_row = next(row for row in evidence if row["id"] == existing.id)
    assert existing_row["status"] == "verified"


def test_file_lock_retries_transient_windows_permission_error(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "transient-lock.jsonl"
    real_open = storage_module.os.open
    attempts = 0

    def flaky_open(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("synthetic transient lock contention")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(storage_module.os, "open", flaky_open)

    storage_module.append_jsonl(path, [{"id": "preserved"}])

    assert attempts == 2
    assert storage_module.read_jsonl(path) == [{"id": "preserved"}]


def test_add_video_is_delegated_source_registration(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "视频如何进入研究？")
    result = add_video(project, "lesson.mp4", topic="课程视频")

    assert result["delegated_to"].endswith("video-knowledge-pipeline")
    sources = list_records(project, "sources")
    assert sources[0]["source_type"] == "video"
    assert sources[0]["path"] == "lesson.mp4"


def test_cli_and_mcp_expose_video_bridge(tmp_path: Path) -> None:
    project = tmp_path / "project"
    assert cli_main(["init", "CLI 是否可用？", "--project", str(project)]) == 0

    tools = list_mcp_tools()
    assert any(tool["name"] == "run_video_knowledge_tool" for tool in tools)
    assert any(tool["name"] == "init_project" for tool in tools)
    assert _parse_json('{"ok": true}') == {"ok": True}
    assert _parse_json("not json") is None


def test_plan_video_knowledge_run_builds_read_only_prepare_command(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "lecture-workspace"

    result = plan_video_knowledge_run(
        "D:/videos/lecture.mp4",
        workspace,
        title="Lecture Test",
        max_frames=80,
    )

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["tool"] == "video-knowledge-pipeline"
    assert "prepare-local-video-run" in result["command"]
    assert "--build-initial-bundle" in result["command"]
    assert "--max-frames" in result["command"]
    assert result["expected_artifacts"]["review_html"].endswith("webui-bundle/review.html")
    assert result["expected_artifacts"]["knowledge_note"].endswith("exports/knowledge-note.md")
    assert "delegation_boundary" in result

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "plan_video_knowledge_run" in tools
    assert call_mcp_tool(
        "plan_video_knowledge_run",
        {"media_path": "D:/videos/lecture.mp4", "workspace": str(workspace), "title": "Lecture Test"},
    )["read_only"] is True

    assert cli_main(["plan-video-knowledge-run", "D:/videos/lecture.mp4", str(workspace), "--title", "Lecture Test"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"][0].endswith("video-knowledge.ps1")


def test_import_video_knowledge_artifacts_adds_review_candidates(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    bundle = tmp_path / "video-run" / "webui-bundle"
    exports = tmp_path / "video-run" / "exports"
    bundle.mkdir(parents=True)
    exports.mkdir(parents=True)
    (bundle / "review.html").write_text("<html>review</html>", encoding="utf-8")
    (exports / "knowledge-note.md").write_text("# 课程知识笔记\n\n- 重要观点：一人公司需要清晰定位。", encoding="utf-8")
    (exports / "full-transcript.md").write_text("完整转录文本", encoding="utf-8")
    init_project(project, "课程视频如何进入研究？")
    claim = add_claim(project, text="一人公司需要清晰定位")

    result = import_video_knowledge_artifacts(project, bundle, title="一人公司课程", claim_id=claim.id)

    assert result["ok"] is True
    assert result["human_review_required"] is True
    assert result["source"]["source_type"] == "video_knowledge"
    assert result["source"]["quality"] == "unknown"
    assert result["evidence"]["status"] == "candidate"
    assert result["evidence"]["relation"] == "unknown"
    assert result["artifacts"]["review_html"]["exists"] is True
    assert Path(result["manifest_path"]).exists()
    payload = _project_payload(project)
    queue_types = {item["item_type"] for item in payload["review_queue"]}
    assert "source_quality" in queue_types
    assert "candidate_evidence" in queue_types

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "import_video_knowledge_artifacts" in tools
    mcp_result = call_mcp_tool("import_video_knowledge_artifacts", {"root": str(project), "bundle_dir": str(bundle), "title": "二次导入"})
    assert mcp_result["source"]["source_type"] == "video_knowledge"

    assert cli_main(["import-video-knowledge-artifacts", str(bundle), "--project", str(project), "--title", "CLI 导入"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["source"]["title"] == "CLI 导入"


def test_video_artifact_status_checks_expected_bundle_files(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "video-run" / "webui-bundle"
    exports = tmp_path / "video-run" / "exports"
    bundle.mkdir(parents=True)
    exports.mkdir(parents=True)
    (bundle / "review.html").write_text("<html>review</html>", encoding="utf-8")
    (exports / "knowledge-note.md").write_text("# note", encoding="utf-8")

    missing = check_video_run_artifacts(bundle)
    assert missing["ok"] is False
    assert "full_transcript" in missing["missing"]

    (exports / "full-transcript.md").write_text("transcript", encoding="utf-8")
    complete = check_video_run_artifacts(bundle)
    assert complete["ok"] is True
    assert complete["artifacts"]["review_html"]["exists"] is True
    assert call_mcp_tool("check_video_run_artifacts", {"bundle_dir": str(bundle)})["ok"] is True

    assert cli_main(["check-video-run-artifacts", str(bundle)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_mcp_core_call(tmp_path: Path) -> None:
    project = tmp_path / "project"
    result = call_mcp_tool("init_project", {"root": str(project), "question": "MCP 是否可用？"})
    assert result["question"] == "MCP 是否可用？"


def test_cli_mcp_call_accepts_json_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    args_file = tmp_path / "args.json"
    args_file.write_text(json.dumps({"root": str(project), "question": "文件参数是否可用？"}, ensure_ascii=False), encoding="utf-8")

    assert cli_main(["mcp-call", "init_project", str(args_file)]) == 0


def test_web_payloads_expose_controller_state_and_tools(tmp_path: Path, synthetic_tool_registry: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "总控台是否可用？")
    add_source(project, title="来源", url="https://example.com")
    add_claim(project, text="总控层应能显示研究状态")

    payload = _project_payload(project)
    assert payload["ok"] is True
    assert payload["project"]["question"] == "总控台是否可用？"
    assert len(payload["sources"]) == 1
    assert len(payload["claims"]) == 1
    assert payload["workflow"]["has_gate_audit"] is False

    tools = _tools_payload()
    assert any(tool["name"] == "question-research-poc" for tool in tools["tools"])
    assert any(tool["name"] == "video-knowledge-pipeline" for tool in tools["tools"])
    assert tools["runtime_config"] == str(RUNTIME_CONFIG_PATH)
    assert tools["web_url"] == web_url()


def test_runtime_config_is_single_web_port_source() -> None:
    config = load_runtime_config()

    assert web_host(config) == "127.0.0.1"
    assert web_port(config) == config["web"]["port"]
    assert web_url(config) == f"http://{config['web']['host']}:{config['web']['port']}"
    assert default_project_root(config) == RUNTIME_CONFIG_PATH.parent.parent / config["project"]["default_root"]


def test_research_plan_can_generate_and_add_claims(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "AI 如何辅助问题导向研究？")

    plan = build_research_plan(project, add_claims=True)

    assert plan["schema"] == "question_research_plan.v1"
    assert len(plan["subquestions"]) >= 6
    assert len(plan["search_tasks"]) >= 7
    assert (project / "research-plan.json").exists()
    assert (project / "notes" / "research-plan.md").exists()
    assert len(list_records(project, "claims")) == len(plan["added_claims"])
    assert read_research_plan(project)["question"] == "AI 如何辅助问题导向研究？"


def test_import_ai_research_result_backfills_records(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "知识类视频如何全量转知识库？")
    result = {
        "sources": [
            {
                "id": "src1",
                "title": "Example source",
                "url": "https://example.com/research",
                "source_type": "web",
                "quality_score": 82,
                "snippet": "A useful source.",
            }
        ],
        "claims": [{"text": "视频知识提取需要同时处理语音和画面。"}],
        "evidence": [
            {
                "source_id": "src1",
                "claim": "视频知识提取需要同时处理语音和画面。",
                "quote_or_paraphrase": "The source discusses audio and visual extraction together.",
                "support_direction": "supports",
                "confidence": 0.9,
            }
        ],
    }

    imported = import_ai_research_result(project, result)

    assert imported["counts"] == {"sources": 1, "claims": 1, "evidence": 1}
    assert list_records(project, "sources")[0]["quality"] == "good"
    assert list_records(project, "evidence")[0]["relation"] == "supports"
    assert list_records(project, "evidence")[0]["confidence"] == "high"


def test_ai_research_import_preserves_provenance_and_is_record_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "provenance-import"
    init_project(project, "候选研究证据能否保留来源路径且保持 fail-closed？")
    result = {
        "sources": [
            {
                "id": "src-provenance",
                "title": "Synthetic local source",
                "url": "local://ai-research-workflow/source-provenance",
                "source_type": "local_fixture",
                "quality_score": 90,
                "verification_status": "verified",
                "published_at": "2026-07-01T00:00:00+00:00",
                "retrieved_at": "2026-07-30T00:00:00+00:00",
                "local_path": "local://fixtures/source-provenance.json",
                "artifact_sha256": "synthetic-source-hash",
            }
        ],
        "claim_table": [
            {
                "id": "claim-provenance",
                "text": "导入成功不等于证据已经通过审核。",
                "verdict": "supported",
            }
        ],
        "evidence": [
            {
                "id": "evidence-provenance",
                "source_id": "src-provenance",
                "claim_id": "claim-provenance",
                "quote_or_paraphrase": "The local adapter preserves candidate evidence for explicit review.",
                "support_direction": "supported",
                "confidence": 0.9,
                "verification_status": "candidate",
                "observed_at": "2026-07-30T00:01:00+00:00",
                "source_path": "local://fixtures/source-provenance.json",
            }
        ],
    }

    first = import_ai_research_result(project, result)
    second = import_ai_research_result(project, result)

    assert first["counts"] == {"sources": 1, "claims": 1, "evidence": 1}
    assert second["counts"] == {"sources": 0, "claims": 0, "evidence": 0}
    source_notes = list_records(project, "sources")[0]["notes"]
    evidence = list_records(project, "evidence")[0]
    for expected in (
        "verification_status: verified",
        "published_at: 2026-07-01T00:00:00+00:00",
        "retrieved_at: 2026-07-30T00:00:00+00:00",
        "local_path: local://fixtures/source-provenance.json",
        "artifact_sha256: synthetic-source-hash",
    ):
        assert expected in source_notes
    assert evidence["status"] == "candidate"
    assert "verification_status: candidate" in evidence["notes"]
    assert "observed_at: 2026-07-30T00:01:00+00:00" in evidence["notes"]
    assert "source_path: local://fixtures/source-provenance.json" in evidence["notes"]
    blocked = export_final_answer(project)
    assert blocked["ok"] is False
    assert "candidate_evidence_not_reviewed" in blocked["blocking_gates"]
def test_mcp_exposes_research_planning_tools(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "MCP 能否调度研究计划？")

    tools = list_mcp_tools()
    assert any(tool["name"] == "build_research_plan" for tool in tools)
    result = call_mcp_tool("build_research_plan", {"root": str(project), "add_claims": True})
    assert result["schema"] == "question_research_plan.v1"


def test_fetch_source_content_saves_artifacts_and_candidate_evidence(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "网页正文如何进入证据库？")
    source = add_source(project, title="测试网页", url="https://example.com/article", quality="unknown")
    claim = add_claim(project, text="网页正文可以生成候选证据")

    def fake_fetch(url: str, **kwargs):
        return {
            "status": "ok",
            "requested_url": url,
            "final_url": url,
            "extractor": "fake",
            "transport": "test",
            "text": "这一段说明网页正文可以生成候选证据，并且需要人工审核。另一个段落不相关。",
        }

    monkeypatch.setattr("question_research_poc.web_fetch_bridge._run_fetch_command", fake_fetch)

    result = fetch_source_content(project, source_id=source.id, claim_id=claim.id, create_candidate_evidence=True)

    assert result["ok"] is True
    assert Path(result["json_path"]).exists()
    assert Path(result["markdown_path"]).exists()
    evidence = list_records(project, "evidence")
    assert len(evidence) == 1
    assert evidence[0]["source_id"] == source.id
    assert evidence[0]["claim_id"] == claim.id
    assert evidence[0]["confidence"] == "low"
    assert evidence[0]["status"] == "candidate"
    assert result["bridge_run"]["tool"] == "web-content-fetcher"
    assert result["bridge_run"]["imported_counts"]["evidence"] == 1
    assert list_bridge_runs(project, tool="web-content-fetcher")["runs"][0]["status"] == "imported"


def test_workflow_route_and_gate_audit_bind_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "如何把课程视频变成可复习知识库？")

    route = route_research_task(project, material_hint="lesson.mp4")
    audit = audit_research_gates(project)

    assert route["route"] == "video_knowledge_ingest"
    assert (project / "task-route.json").exists()
    assert (project / "notes" / "task-route.md").exists()
    assert audit["ok"] is False
    assert audit["can_proceed"] is False
    assert audit["next_gate"]
    assert audit["gate_contract_source"]["type"] == "adapted_local_contract"
    assert any(step["gate_id"] == "research_plan_present" for step in audit["next_steps"])
    assert any(item["id"] == "research_plan_present" for item in audit["blockers"])
    assert (project / "gate-audit.json").exists()
    assert (project / "workflow-next-steps.json").exists()
    assert (project / "notes" / "workflow-gate-audit.md").exists()
    assert (project / "notes" / "workflow-next-steps.md").exists()


def test_multi_perspective_review_writes_review_fallback_and_boundaries(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "AI 如何辅助问题导向研究？")
    source = add_source(project, title="来源", url="https://example.com", quality="good")
    claim = add_claim(project, text="研究需要反证检查")
    evidence = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="材料提到反证检查", relation="supports")
    review_evidence(project, evidence_id=evidence.id, status="verified", confidence="high")

    review = run_multi_perspective_review(project)

    assert len(review["perspectives"]) >= 4
    assert any(item["tool"] == "web-content-fetcher" for item in review["tool_boundaries"])
    assert (project / "multi-perspective-review.json").exists()
    assert (project / "notes" / "multi-perspective-review.md").exists()
    assert (project / "notes" / "fallback-and-tool-boundary.md").exists()


def test_reader_persona_review_and_final_result_chain(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "总控流程什么时候可以最终交付？")
    build_research_plan(project, add_claims=True)
    route_research_task(project)
    run_multi_perspective_review(project)

    blocked = audit_research_gates(project, target_stage="final_answer")
    assert blocked["ok"] is False
    assert "reader-persona-review.md" in blocked["missing_result_files"]
    assert any(step["gate_id"] == "reader_persona_review_present" for step in blocked["next_steps"])

    persona = run_reader_persona_review(project)
    checked = audit_research_gates(project, target_stage="final_answer")

    assert persona["schema"] == "reader_persona_review.v1"
    assert len(persona["personas"]) == 4
    assert (project / "reader-persona-review.json").exists()
    assert (project / "notes" / "reader-persona-review.md").exists()
    assert "reader-persona-review.md" not in checked["missing_result_files"]
    assert (project / "workflow-contract.json").exists()
    assert (project / "notes" / "workflow-contract.md").exists()


def test_workflow_engine_and_mcp_expose_flow_tools(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "流程工程是否可用？")
    build_research_plan(project, add_claims=True)

    result = run_workflow_engine(project)
    tools = list_mcp_tools()

    assert result["ok"] is True
    assert result["gate_contract_source"]["pattern"].startswith("readiness payload")
    assert "persona_review" in result
    assert "gate_audit" in result
    assert any(tool["name"] == "route_research_task" for tool in tools)
    assert any(tool["name"] == "audit_research_gates" for tool in tools)
    assert any(tool["name"] == "run_reader_persona_review" for tool in tools)
    assert call_mcp_tool("audit_research_gates", {"root": str(project), "write": False})["schema"] == "research_gate_audit.v1"

    payload = _project_payload(project)
    assert payload["workflow"]["has_route"] is True
    assert payload["workflow"]["has_gate_audit"] is True
    assert payload["workflow"]["has_next_steps"] is True
    assert payload["workflow"]["gate_audit"]["schema"] == "research_gate_audit.v1"
    artifacts = payload["workflow"]["artifacts"]
    assert any(item["id"] == "task_route" and item["complete"] for item in artifacts)
    assert any(item["id"] == "gate_audit" and item["complete"] for item in artifacts)
    assert isinstance(payload["workflow"]["gate_details"], dict)


def test_review_queue_and_gate_details_track_human_work(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "审核队列如何工作？")
    unknown_source = add_source(project, title="未标来源", url="https://example.com/a")
    poor_source = add_source(project, title="低质量来源", url="https://example.com/b", quality="poor")
    claim = add_claim(project, text="需要证据的主张")
    unsupported_claim = add_claim(project, text="还没有证据的主张")
    candidate = add_evidence(project, claim_id=claim.id, source_id=poor_source.id, quote_or_note="低质量来源里的说法")
    audit_research_gates(project)

    payload = _project_payload(project)
    queue_types = {item["item_type"] for item in payload["review_queue"]}

    assert "source_quality" in queue_types
    assert "candidate_evidence" in queue_types
    assert "poor_source_evidence" in queue_types
    assert "claim_without_evidence" in queue_types
    assert "missing_counter_evidence" in queue_types
    assert any(item["source_id"] == unknown_source.id for item in payload["review_queue"] if item["item_type"] == "source_quality")
    assert any(item["evidence_id"] == candidate.id for item in payload["review_queue"] if item["item_type"] == "candidate_evidence")
    assert any(item["claim_id"] == unsupported_claim.id for item in payload["review_queue"] if item["item_type"] == "claim_without_evidence")
    assert all(item["requires_human_confirmation"] is True for item in payload["review_queue"] if item["item_type"] != "missing_counter_evidence")
    assert all(item["requires_human_confirmation"] is False for item in payload["review_queue"] if item["item_type"] == "missing_counter_evidence")
    assert all(item["suggested_ui_focus"] for item in payload["review_queue"])
    source_quality_detail = payload["workflow"]["gate_details"]["source_quality_reviewed"]
    evidence_detail = payload["workflow"]["gate_details"]["evidence_present"]
    verified_detail = payload["workflow"]["gate_details"]["verified_evidence_present"]
    assert source_quality_detail["record_count"] == 1
    assert source_quality_detail["next_human_action"]
    assert source_quality_detail["entrypoints"]["mcp"]
    assert source_quality_detail["records"][0]["record_ref"] == f"source:{unknown_source.id}"
    assert evidence_detail["record_count"] == 1
    assert evidence_detail["records"][0]["record_id"] == unsupported_claim.id
    assert verified_detail["record_count"] >= 1
    assert verified_detail["why"]
    assert get_gate_details(project, "source_quality_reviewed")["detail"]["records"][0]["ui_focus"] == "reviewQueuePanel"
    assert get_review_queue(project, "source_quality")["items"][0]["allowed_actions"] == ["review_source_quality", "open_source"]
    dashboard = payload["dashboard"]
    assert dashboard["metrics"]["sources"] == 2
    assert dashboard["source_quality"]["unknown"] == 1
    assert dashboard["metrics"]["claim_coverage_percent"] == 50
    assert dashboard["metrics"]["verified_claim_coverage_percent"] == 0
    assert dashboard["gaps"]

    review_source(project, source_id=unknown_source.id, quality="good", reason="测试标注")
    review_evidence(project, evidence_id=candidate.id, status="verified", relation="supports", confidence="medium")
    payload = _project_payload(project)
    queue_types = {item["item_type"] for item in payload["review_queue"]}

    assert "source_quality" not in queue_types
    assert "candidate_evidence" not in queue_types
    assert get_project_dashboard(project)["metrics"]["verified_claim_coverage_percent"] == 50


def test_review_source_records_general_review_note(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "来源审核备注如何记录？")
    source = add_source(project, title="待审来源", url="https://example.com")

    review = review_source(project, source_id=source.id, quality="mixed", reason="信息有用，但需要交叉验证。")

    reviews = list_records(project, "reviews")
    sources = list_records(project, "sources")
    assert review.reason == "信息有用，但需要交叉验证。"
    assert sources[0]["quality_reason"] == "信息有用，但需要交叉验证。"
    assert reviews[-1]["kind"] == "source"
    assert reviews[-1]["note"] == "信息有用，但需要交叉验证。"


def test_review_state_is_shared_by_web_agent_and_export(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "共享审核状态是否一致？")
    source = add_source(project, title="未标来源", url="https://example.com")
    claim = add_claim(project, text="共享状态应避免 UI 和 MCP 漂移")
    evidence = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选证据")
    audit_research_gates(project)

    shared_workflow = build_workflow_payload(project)
    shared_queue = build_review_queue(project)
    web_payload = _project_payload(project)
    agent_status = get_project_status(project)
    pack = export_research_pack(project)

    assert shared_workflow["review_queue_count"] == len(shared_queue)
    assert web_payload["workflow"]["gate_details"] == shared_workflow["gate_details"]
    assert web_payload["review_queue"] == shared_queue
    assert agent_status["counts"]["review_queue"] == len(shared_queue)
    assert pack["review_queue_count"] == len(shared_queue)
    assert any(item["evidence_id"] == evidence.id for item in shared_queue if item["item_type"] == "candidate_evidence")


def test_project_overview_collects_cockpit_summary(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "总览页应该展示什么？")
    route_research_task(project)
    source = add_source(project, title="可信来源", url="https://example.com", quality="good")
    weak_source = add_source(project, title="待审来源", url="https://example.com/weak")
    claim = add_claim(project, text="总览页需要显示主张证据关系")
    unsupported = add_claim(project, text="这个主张暂时没有证据")
    evidence = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="来源支持总览页")
    add_evidence(project, claim_id=claim.id, source_id=weak_source.id, quote_or_note="候选补充材料")
    review_evidence(project, evidence_id=evidence.id, status="verified", relation="supports", confidence="high")
    audit_research_gates(project)

    overview = build_project_overview(project)

    assert overview["schema"] == "question_research_project_overview.v1"
    assert overview["question"] == "总览页应该展示什么？"
    assert overview["metrics"]["sources"] == 2
    assert overview["source_quality"]["unknown"] == 1
    assert overview["gate_summary"]["failed"] >= 1
    assert overview["review_queue"]["count"] >= 1
    assert any(item["claim_id"] == claim.id and item["coverage_status"] == "verified_without_counter_context" for item in overview["claim_evidence"])
    assert any(item["claim_id"] == unsupported.id and item["coverage_status"] == "missing_evidence" for item in overview["claim_evidence"])
    assert any(item["id"] == "task_route" for item in overview["important_artifacts"])
    assert get_project_overview(project)["schema"] == "question_research_project_overview.v1"
    assert _project_payload(project)["overview"]["claim_evidence"][0]["claim_id"] in {claim.id, unsupported.id}

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "get_project_overview" in tools
    assert call_mcp_tool("get_project_overview", {"root": str(project)})["gate_summary"]["failed"] >= 1
    assert cli_main(["get-project-overview", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_project_overview.v1"


def test_completeness_audit_blocks_premature_final_answer(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "完整性检查如何防止过早总结？")
    unknown = add_source(project, title="未审核视频知识包", path="D:/runs/lesson/webui-bundle", source_type="video", quality="unknown")
    poor = add_source(project, title="低质量网页", url="https://example.com", quality="poor")
    claim = add_claim(project, text="一人公司需要系统化积累知识")
    candidate = add_evidence(project, claim_id=claim.id, source_id=unknown.id, quote_or_note="视频里提到要建立知识系统", relation="supports")
    poor_evidence = add_evidence(project, claim_id=claim.id, source_id=poor.id, quote_or_note="低质量来源也提了类似观点", relation="context")
    review_evidence(project, evidence_id=poor_evidence.id, status="verified", confidence="low")
    (project / "notes").mkdir(exist_ok=True)
    (project / "notes" / "answer-draft.md").write_text("draft", encoding="utf-8")

    audit = audit_research_completeness(project)

    assert audit["schema"] == "question_research_completeness_audit.v1"
    assert audit["ready_for_answer"] is False
    assert "unknown_source_quality" in audit["blocking_gates"]
    assert "candidate_evidence_not_reviewed" in audit["blocking_gates"]
    assert "poor_source_evidence" in audit["blocking_gates"]
    assert "imported_video_material_not_reviewed" in audit["blocking_gates"]
    assert audit["coverage"]["candidate_evidence"] == 1
    assert audit["coverage"]["claims_with_counter_or_context"] == 1
    assert any(item["item_type"] == "draft_before_gate_pass" for item in audit["items"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "audit_completeness" in tools
    assert call_mcp_tool("audit_completeness", {"root": str(project)})["ready_for_answer"] is False
    assert cli_main(["audit-completeness", "--project", str(project)]) == 0
    captured = capsys.readouterr()
    assert "question_research_completeness_audit.v1" in captured.out

    review_evidence(project, evidence_id=candidate.id, status="verified", confidence="medium")
    reviewed = audit_research_completeness(project)
    assert reviewed["coverage"]["candidate_evidence"] == 0


def test_final_answer_export_is_guarded_by_completeness_audit(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "最终答案什么时候可以导出？")
    source = add_source(project, title="待审来源", url="https://example.com/source", quality="unknown")
    claim = add_claim(project, text="最终答案必须经过完整性审计。")
    add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选证据", relation="supports")

    blocked = export_final_answer(project)

    assert blocked["ok"] is False
    assert blocked["schema"] == "question_research_final_answer_export.v1"
    assert blocked["exported"] is False
    assert blocked["blocked"] is True
    assert "unknown_source_quality" in blocked["blocking_gates"]
    assert not (project / "exports" / "final-answer" / "final-answer.md").exists()

    incomplete = export_final_answer(project, allow_incomplete=True)
    assert incomplete["ok"] is True
    assert incomplete["ready_for_answer"] is False
    assert incomplete["allow_incomplete"] is True
    incomplete_text = Path(incomplete["files"]["markdown"]).read_text(encoding="utf-8")
    assert "Status: incomplete_export" in incomplete_text
    assert "unknown_source_quality" in incomplete_text

    ready_project = tmp_path / "ready-project"
    init_project(ready_project, "通过审计后才能导出最终答案。")
    good = add_source(ready_project, title="高质量来源", url="https://example.com/good", quality="good")
    ready_claim = add_claim(ready_project, text="完整性审计通过后可以导出。")
    support = add_evidence(ready_project, claim_id=ready_claim.id, source_id=good.id, quote_or_note="支持证据", relation="supports")
    context = add_evidence(ready_project, claim_id=ready_claim.id, source_id=good.id, quote_or_note="上下文证据", relation="context")
    review_source(ready_project, source_id=good.id, quality="good", reason="测试来源")
    review_evidence(ready_project, evidence_id=support.id, status="verified", relation="supports", confidence="high")
    review_evidence(ready_project, evidence_id=context.id, status="verified", relation="context", confidence="medium")

    ready = export_final_answer(ready_project)
    assert ready["ok"] is True
    assert ready["ready_for_answer"] is True
    ready_text = Path(ready["files"]["markdown"]).read_text(encoding="utf-8")
    assert "Status: ready_for_answer" in ready_text

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "export_final_answer" in tools
    assert call_mcp_tool("export_final_answer", {"root": str(project)})["ok"] is False
    assert call_mcp_tool("export_final_answer", {"root": str(project), "allow_incomplete": True})["allow_incomplete"] is True
    assert cli_main(["export-final-answer", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert cli_main(["export-final-answer", "--project", str(project), "--allow-incomplete"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_incomplete"] is True


def test_agent_manifest_maps_ui_cli_mcp_and_boundaries(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "Agent 如何稳定调用总控台？")

    manifest = build_agent_manifest(project)
    actions = {item["id"]: item for item in manifest["ui_actions"]}

    assert manifest["schema"] == "question_research_agent_manifest.v1"
    assert manifest["runtime_config"].endswith("config\\runtime.json") or manifest["runtime_config"].endswith("config/runtime.json")
    assert "get_project_status" in manifest["recommended_agent_flow"]
    assert "get_project_overview" in manifest["recommended_agent_flow"]
    assert "audit_cockpit_readiness when checking controller capability gaps" in manifest["recommended_agent_flow"]
    assert "audit_completeness before final-answer-like output" in manifest["recommended_agent_flow"]
    assert "export_final_answer only after audit_completeness is ready, or with explicit incomplete marking" in manifest["recommended_agent_flow"]
    assert "run_work_queue_item only for explicit tool_action entries; default dry-run" in manifest["recommended_agent_flow"]
    assert "generate_graph_candidates/list_graph_candidates when graph review is needed" in manifest["recommended_agent_flow"]
    assert "run_next_step for agent-safe gates only" in manifest["recommended_agent_flow"]
    assert actions["project_overview"]["cli"].startswith(".\\scripts\\research-poc.ps1 get-project-overview")
    assert actions["project_overview"]["mcp"] == "get_project_overview"
    assert actions["build_demo_project"]["mcp"] == "build_demo_project"
    assert actions["audit_cockpit_readiness"]["mcp"] == "audit_cockpit_readiness"
    assert actions["review_source"]["agent_callable"] is False
    assert actions["review_source"]["human_review_boundary"] is True
    assert actions["search_import"]["agent_callable"] is True
    assert actions["run_work_queue_item"]["mcp"] == "run_work_queue_item"
    assert actions["generate_graph_candidates"]["mcp"] == "generate_graph_candidates"
    assert actions["review_graph_candidate"]["agent_callable"] is False
    assert actions["review_graph_candidate"]["human_review_boundary"] is True
    assert actions["export_reviewed_graph"]["mcp"] == "export_reviewed_graph"
    assert actions["export_final_answer"]["mcp"] == "export_final_answer"
    assert any("Candidate evidence" in item for item in manifest["human_review_boundaries"])
    assert any("Work queue execution only runs explicit allowlisted tool_action entries" in item for item in manifest["human_review_boundaries"])
    assert any("Graph candidates require explicit human acceptance" in item for item in manifest["human_review_boundaries"])
    assert any("Final-answer export is blocked" in item for item in manifest["human_review_boundaries"])
    assert any("Do not auto-mark evidence" in item for item in manifest["forbidden_operations"])
    assert any("Do not auto-accept graph candidates" in item for item in manifest["forbidden_operations"])
    assert any("Do not present draft or incomplete export as a final answer" in item for item in manifest["forbidden_operations"])
    assert any(item["artifact"] == "tool_bridge_status" for item in manifest["read_artifact_endpoints"])
    assert any(item["artifact"] == "completeness_audit" for item in manifest["read_artifact_endpoints"])
    assert any(item["artifact"] == "cockpit_readiness" for item in manifest["read_artifact_endpoints"])
    assert any(item["artifact"] == "final_answer_export" for item in manifest["read_artifact_endpoints"])
    assert any(item["artifact"] == "work_queue" for item in manifest["read_artifact_endpoints"])
    assert any(item["artifact"] == "graph_candidates" for item in manifest["read_artifact_endpoints"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "get_agent_manifest" in tools
    assert call_mcp_tool("get_agent_manifest", {"root": str(project)})["schema"] == "question_research_agent_manifest.v1"
    assert cli_main(["get-agent-manifest", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_agent_manifest.v1"


def test_cockpit_readiness_audits_controller_capabilities(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    build_demo_project(project)

    readiness = audit_cockpit_readiness(project)

    assert readiness["schema"] == "question_research_cockpit_readiness.v1"
    assert readiness["summary"]["total"] >= 20
    assert readiness["summary"]["percent"] >= 90
    sections = {section["id"]: section for section in readiness["sections"]}
    assert sections["gate_workbench"]["status"] == "pass"
    assert sections["review_queue"]["status"] == "pass"
    assert sections["external_tool_bridge"]["status"] == "pass"
    assert sections["agent_interfaces"]["status"] == "pass"

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "audit_cockpit_readiness" in tools
    assert call_mcp_tool("audit_cockpit_readiness", {"root": str(project)})["schema"] == "question_research_cockpit_readiness.v1"
    assert cli_main(["audit-cockpit-readiness", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_cockpit_readiness.v1"


def test_graph_candidates_generate_review_export_and_interfaces(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "研究驾驶舱如何形成知识图谱？")
    source = add_source(project, title="课程笔记", url="https://example.com/lesson", quality="good")
    claim = add_claim(project, text="图谱边必须经过人工审核。")
    evidence = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选边先进入审核队列。", relation="supports")

    generated = generate_graph_candidates(project)

    assert generated["schema"] == "question_research_graph_candidates.v1"
    assert generated["added_count"] >= 3
    assert generated["counts"]["total"] >= 4
    assert generated["human_review_required"] is True
    assert Path(generated["path"]).exists()
    assert all(edge["status"] == "candidate" for edge in generated["added"])
    assert all(edge["created_by"] for edge in generated["added"])
    assert all("reason" in edge for edge in generated["added"])
    assert all(edge["human_review_required"] is True for edge in generated["added"])
    assert any(edge["evidence_ref"] == evidence.id for edge in generated["added"])

    listed = list_graph_candidates(project, status="candidate")
    assert listed["counts"]["candidate"] == len(listed["candidates"])
    assert list_graph_candidates(project, edge_type="source_contains_evidence")["counts"]["total"] >= 1

    target = next(edge for edge in listed["candidates"] if edge["edge_type"] == "source_contains_evidence")
    review = review_graph_candidate(project, from_id=target["from_id"], to_id=target["to_id"], status="accepted", note="人工确认", reviewer="tester")
    assert review["ok"] is True
    accepted = list_graph_candidates(project, status="accepted")["candidates"]
    assert any(edge["from_id"] == target["from_id"] and edge["to_id"] == target["to_id"] and edge["human_review_required"] is False for edge in accepted)

    exported = export_reviewed_graph(project)
    assert exported["schema"] == "question_research_reviewed_graph_export.v1"
    assert exported["counts"]["total"] >= 1
    assert all(edge["status"] in {"accepted", "verified"} for edge in exported["edges"])
    assert Path(exported["files"]["json"]).exists()
    markdown = Path(exported["files"]["markdown"]).read_text(encoding="utf-8")
    assert "Reviewed Graph" in markdown
    assert "source_contains_evidence" in markdown

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"generate_graph_candidates", "list_graph_candidates", "review_graph_candidate", "export_reviewed_graph"}.issubset(tools)
    assert call_mcp_tool("list_graph_candidates", {"root": str(project)})["schema"] == "question_research_graph_candidates.v1"
    assert call_mcp_tool("export_reviewed_graph", {"root": str(project)})["schema"] == "question_research_reviewed_graph_export.v1"

    assert cli_main(["generate-graph-candidates", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_graph_candidates.v1"
    assert cli_main(["list-graph-candidates", "--project", str(project), "--status", "accepted"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["accepted"] >= 1
    assert cli_main(["export-reviewed-graph", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_reviewed_graph_export.v1"


def test_research_stage_classifier_tracks_project_progress(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "研究阶段如何判断？")

    assert classify_research_stage(project)["stage_id"] == "question_defined"

    build_research_plan(project)
    assert classify_research_stage(project)["stage_id"] == "research_plan_ready"

    source = add_source(project, title="来源", url="https://example.com")
    assert classify_research_stage(project, review_queue=build_review_queue(project))["stage_id"] == "sources_collected"

    review_source(project, source_id=source.id, quality="good", reason="测试")
    assert classify_research_stage(project)["stage_id"] == "source_quality_reviewed"

    claim = add_claim(project, text="阶段状态应该解释当前卡点")
    evidence = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选证据", relation="supports")
    stage = classify_research_stage(project, review_queue=build_review_queue(project))
    assert stage["stage_id"] == "claims_extracted"
    assert stage["blocking_gate"] == "verified_evidence_present"
    assert "不得自动通过证据" in stage["next_agent_action"]

    review_evidence(project, evidence_id=evidence.id, status="verified", relation="supports", confidence="medium")
    assert classify_research_stage(project)["stage_id"] == "evidence_reviewed"

    pack = export_research_pack(project)
    assert pack["ok"] is True
    assert classify_research_stage(project)["stage_id"] == "export_ready"


def test_demo_project_builder_creates_non_empty_cockpit_fixture(tmp_path: Path, capsys) -> None:
    project = tmp_path / "demo-project"

    demo = build_demo_project(project)

    assert demo["schema"] == "question_research_demo_project.v1"
    assert demo["counts"]["sources"] == 4
    assert demo["counts"]["claims"] == 3
    assert demo["counts"]["review_queue"] >= 4
    assert demo["counts"]["graph_candidates"] >= 1
    assert demo["counts"]["tool_runs"] >= 1
    sources = list_records(project, "sources")
    claims = list_records(project, "claims")
    evidence = list_records(project, "evidence")
    review_queue = build_review_queue(project)
    bridge = build_tool_bridge_status(project)

    assert {"good", "poor", "unknown"}.issubset({source["quality"] for source in sources})
    assert any(source["source_type"] == "video_bundle" for source in sources)
    assert any(item["status"] == "verified" for item in evidence)
    assert any(item["status"] == "candidate" for item in evidence)
    assert any(item["relation"] == "context" for item in evidence)
    assert any(item["item_type"] == "claim_without_evidence" for item in review_queue)
    assert any(item["item_type"] == "candidate_evidence" for item in review_queue)
    assert any(item["item_type"] == "poor_source_evidence" for item in review_queue)
    assert any(run["tool"] == "web-content-fetcher" for run in bridge["recent_runs"])
    assert (project / "fetched-sources" / "demo-source.md").exists()
    assert (project / "gate-audit.json").exists()
    assert claims

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "build_demo_project" in tools
    mcp_project = tmp_path / "demo-mcp"
    assert call_mcp_tool("build_demo_project", {"root": str(mcp_project)})["schema"] == "question_research_demo_project.v1"
    assert cli_main(["build-demo-project", "--project", str(tmp_path / "demo-cli")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_demo_project.v1"


def test_research_stage_does_not_treat_empty_pack_as_export_ready(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "空研究包不能掩盖缺口")
    output = project / "exports" / "research-pack"
    output.mkdir(parents=True)
    for name in ["research-brief.md", "source-quality-table.md", "evidence-table.md", "open-questions.md", "next-actions.md"]:
        (output / name).write_text("empty", encoding="utf-8")

    stage = classify_research_stage(project)

    assert stage["stage_id"] == "question_defined"
    assert stage["blocking_gate"] == "research_plan_present"


def test_agent_status_tools_and_next_step_boundaries(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "Agent 如何推进下一步？")
    audit_research_gates(project)

    status = get_project_status(project)
    assert status["counts"]["review_queue"] == 0
    assert status["workflow"]["blocker_count"] >= 1
    assert status["stage"]["stage_id"] in {"question_defined", "research_plan_ready"}

    result = run_next_step(project, "research_plan_present")
    assert result["status"] == "executed"
    assert (project / "research-plan.json").exists()

    human = run_next_step(project, "source_quality_reviewed")
    assert human["status"] in {"human_required", "not_found"}

    artifact = read_workflow_artifact(project, "research_plan")
    assert "研究计划" in artifact["content"]

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "get_project_status" in tools
    assert "get_project_dashboard" in tools
    assert "get_tool_health_dashboard" in tools
    assert "get_gate_details" in tools
    assert "get_review_queue" in tools
    assert "run_next_step" in tools
    assert "read_workflow_artifact" in tools
    assert call_mcp_tool("get_project_status", {"root": str(project)})["ok"] is True
    assert call_mcp_tool("get_project_dashboard", {"root": str(project)})["metrics"]["claims"] >= 1
    assert call_mcp_tool("get_tool_health_dashboard", {})["summary"]["total"] >= 4

    assert cli_main(["get-project-status", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert cli_main(["get-project-dashboard", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "metrics" in payload
    assert cli_main(["get-tool-health-dashboard"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "video-knowledge-pipeline" in {tool["name"] for tool in payload["tools"]}


def test_agent_runbook_builds_safe_commands_and_boundaries(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "Agent 下一步怎么稳定推进？")
    source = add_source(project, title="待审来源", url="https://example.com")
    claim = add_claim(project, text="Agent 不能自动通过证据")
    add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选证据")
    audit_research_gates(project)

    runbook = build_agent_runbook(project)

    assert runbook["ok"] is True
    assert runbook["schema"] == "question_research_agent_runbook.v1"
    assert runbook["commands"]
    assert runbook["human_tasks"]
    assert any("get-review-queue" in command["command"] for command in runbook["commands"])
    bridge_commands = [command for command in runbook["commands"] if command.get("tool_action", {}).get("kind") == "bridge_action"]
    assert any(command["tool_action"]["action"] == "web_fetch_source" for command in bridge_commands)
    assert any("不得把候选证据自动升级" in item for item in runbook["operator_boundaries"])
    assert "Human Tasks" in runbook["markdown"]
    queued = enqueue_bridge_actions(project)
    assert queued["ok"] is True
    assert queued["added_count"] >= 1
    assert any(task.get("tool_action", {}).get("kind") == "bridge_action" for task in queued["tasks"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "build_agent_runbook" in tools
    assert call_mcp_tool("enqueue_bridge_actions", {"root": str(project)})["ok"] is True
    assert call_mcp_tool("build_agent_runbook", {"root": str(project)})["schema"] == "question_research_agent_runbook.v1"
    assert cli_main(["build-agent-runbook", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_agent_runbook.v1"


def test_export_research_pack_writes_human_readable_files_and_interfaces(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "如何评估一个知识视频？")
    source = add_source(project, title="课程视频", url="file:///lesson.mp4", quality="unknown")
    claim = add_claim(project, text="视频提出了一人公司的核心判断。")
    evidence = add_evidence(
        project,
        claim_id=claim.id,
        source_id=source.id,
        quote_or_note="讲者认为时间不应该继续被低价出售。",
        relation="supports",
    )
    audit_research_gates(project)

    result = export_research_pack(project)

    assert result["ok"] is True
    assert result["schema"] == "question_research_pack.v1"
    assert result["human_review_required"] is True
    assert result["review_queue_count"] >= 2
    output = project / "exports" / "research-pack"
    for name in [
        "research-brief.md",
        "source-quality-table.md",
        "evidence-table.md",
        "open-questions.md",
        "next-actions.md",
    ]:
        assert (output / name).exists()
    brief = (output / "research-brief.md").read_text(encoding="utf-8")
    evidence_table = (output / "evidence-table.md").read_text(encoding="utf-8")
    open_questions = (output / "open-questions.md").read_text(encoding="utf-8")
    assert "如何评估一个知识视频？" in brief
    assert "Human review required" in brief
    assert "课程视频" in brief
    assert evidence.id in evidence_table
    assert "candidate" in evidence_table
    assert "source_quality" in open_questions

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "export_research_pack" in tools
    mcp_result = call_mcp_tool("export_research_pack", {"root": str(project)})
    assert mcp_result["files"]["research_brief"].endswith("research-brief.md")

    assert cli_main(["export-research-pack", "--project", str(project)]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["schema"] == "question_research_pack.v1"


def test_research_pack_distinguishes_answer_ready_from_workflow_pack_complete(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "答案 ready 和 workflow pack complete 如何区分？")
    source = add_source(project, title="权威来源", url="https://example.com", quality="good")
    claim = add_claim(project, text="核心主张需要支持和上下文证据。")
    support = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="支持证据", relation="supports")
    context = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="上下文证据", relation="context")
    review_evidence(project, evidence_id=support.id, status="verified", confidence="high")
    review_evidence(project, evidence_id=context.id, status="verified", confidence="medium")

    completeness = audit_research_completeness(project)
    pack = export_research_pack(project)

    assert completeness["ready_for_answer"] is True
    assert completeness["blocking_gates"] == []
    assert pack["answer_ready"] is True
    assert pack["workflow_pack_complete"] is False
    assert pack["answer_readiness"]["ready_for_answer"] is True
    assert "Answer readiness 已通过" in pack["next_actions"][0]


def test_knowledge_base_handoff_exports_are_review_first(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    vault = tmp_path / "obsidian-vault"
    init_project(project, "研究结果如何进入知识库？")
    source = add_source(project, title="课程视频", url="file:///lesson.mp4", quality="unknown")
    claim = add_claim(project, text="知识库写入需要人工审核。")
    add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选证据不能直接成为结论。")
    export_research_pack(project)

    obsidian = export_research_pack_to_obsidian(project, vault, folder="AI Research/审核包")
    handoff = create_logseq_review_handoff(project)

    assert obsidian["ok"] is True
    assert obsidian["human_review_required"] is True
    assert obsidian["direct_write"] is False
    assert (vault / "AI Research" / "审核包" / "research-brief.md").exists()
    assert "LOGSEQ_API_TOKEN" not in (vault / "AI Research" / "审核包" / "research-brief.md").read_text(encoding="utf-8")
    assert handoff["ok"] is True
    assert handoff["direct_write"] is False
    assert handoff["human_review_required"] is True
    handoff_text = Path(handoff["path"]).read_text(encoding="utf-8")
    assert "logseq-api.ps1 status" in handoff_text
    assert "不直接写入 Logseq" in handoff_text
    assert "LOGSEQ_API_TOKEN" not in handoff_text

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "export_research_pack_to_obsidian" in tools
    assert "create_logseq_review_handoff" in tools
    assert call_mcp_tool("export_research_pack_to_obsidian", {"root": str(project), "vault": str(vault), "folder": "AI Research/MCP"})["direct_write"] is False
    assert call_mcp_tool("create_logseq_review_handoff", {"root": str(project)})["direct_write"] is False

    assert cli_main(["export-research-pack-obsidian", "--project", str(project), "--vault", str(vault), "--folder", "AI Research/CLI"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["direct_write"] is False
    assert cli_main(["create-logseq-review-handoff", "--project", str(project)]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["human_review_required"] is True


def test_source_inbox_accepts_and_imports_candidate_artifacts(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "资料收件箱如何工作？")

    video = add_inbox_item(project, kind="video_bundle", title="课程视频", location="D:/runs/lecture/webui-bundle", source_tool="video-knowledge-pipeline")
    web = add_inbox_item(project, kind="web_page", title="网页资料", url="https://example.com/article", source_tool="web-content-fetcher")

    items = list_inbox_items(project)
    assert {item["kind"] for item in items} == {"video_bundle", "web_page"}
    assert all(item["import_status"] == "candidate" for item in items)

    imported = import_inbox_item_as_source(project, video["id"])
    assert imported["ok"] is True
    assert imported["human_review_required"] is True
    assert imported["source"]["quality"] == "unknown"
    assert imported["item"]["import_status"] == "imported"
    assert list_records(project, "sources")[0]["source_type"] == "video_bundle"

    rejected = reject_inbox_item(project, web["id"], note="重复资料")
    assert rejected["import_status"] == "rejected"
    assert rejected["review_note"] == "重复资料"

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "add_source_inbox_item" in tools
    assert "list_source_inbox" in tools
    assert "import_source_inbox_item" in tools
    assert "reject_source_inbox_item" in tools
    assert call_mcp_tool("list_source_inbox", {"root": str(project)})["counts"]["total"] == 2

    assert cli_main(["add-source-inbox-item", "--project", str(project), "--kind", "search_result", "--title", "搜索结果", "--url", "https://example.com/search"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["import_status"] == "candidate"
    assert cli_main(["list-source-inbox", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["candidate"] >= 1


def test_work_queue_tracks_agent_safe_and_human_tasks(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "工作队列如何让 Agent 稳定推进？")

    task = enqueue_task(project, kind="fetch_source", title="抓取来源", command=".\\scripts\\research-poc.ps1 plan-fetch-source-content --project X")
    human = enqueue_task(project, kind="review_source", title="审核来源", command="", status="needs_human", human_boundary="需要人工判定来源质量。")

    assert task["status"] == "pending"
    assert human["status"] == "needs_human"
    assert list_tasks(project)[0]["kind"] == "fetch_source"
    assert update_task_status(project, task["id"], "done")["status"] == "done"

    runbook_result = enqueue_runbook_tasks(project)
    assert runbook_result["ok"] is True
    assert runbook_result["schema"] == "question_research_work_queue.v1"
    assert runbook_result["counts"]["pending"] >= 1
    assert Path(runbook_result["path"]).exists()
    executable_tasks = [task for task in runbook_result["tasks"] if task.get("tool_action")]
    assert executable_tasks
    assert run_work_queue_item(project, executable_tasks[0]["id"])["tool_result"]["executed"] is False

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "enqueue_runbook_tasks" in tools
    assert "list_work_queue" in tools
    assert "update_work_queue_item" in tools
    assert call_mcp_tool("enqueue_runbook_tasks", {"root": str(project)})["ok"] is True
    assert call_mcp_tool("list_work_queue", {"root": str(project)})["schema"] == "question_research_work_queue.v1"

    assert cli_main(["enqueue-runbook-tasks", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_work_queue.v1"
    assert cli_main(["list-work-queue", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["total"] >= 1


def test_tool_executor_is_dry_run_and_whitelisted(tmp_path: Path, synthetic_tool_registry: Path, capsys) -> None:
    health = run_local_tool_action("video-knowledge-pipeline", "health")

    assert health["ok"] is True
    assert health["schema"] == "question_research_tool_action.v1"
    assert health["dry_run"] is True
    assert health["executed"] is False
    assert "asr-env-status" in health["command"]

    discover = run_local_tool_action("video-knowledge-pipeline", "discover")
    assert discover["executed"] is False
    assert discover["artifact_paths"]

    download = run_local_tool_action("video-download-orchestrator", "download_plan", args={"url": "https://example.com/video"})
    assert download["dry_run"] is True
    assert "--dry-run" in download["command"]

    try:
        run_local_tool_action("video-knowledge-pipeline", "shell_anything")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("unlisted action should fail")

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "run_local_tool_action" in tools
    assert call_mcp_tool("run_local_tool_action", {"tool_id": "video-knowledge-pipeline", "action": "health"})["executed"] is False

    assert cli_main(["run-local-tool-action", "video-knowledge-pipeline", "health"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True


def test_work_queue_executes_only_explicit_tool_actions_and_writes_artifacts(tmp_path: Path, synthetic_tool_registry: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "队列如何安全执行本地工具？")
    manual = enqueue_task(project, kind="agent_command", title="普通命令", command="echo unsafe")
    task = enqueue_task(
        project,
        kind="tool_action",
        title="视频工具健康检查",
        tool_action={"tool_id": "video-knowledge-pipeline", "action": "health", "args": {}},
    )

    manual_result = run_work_queue_item(project, manual["id"])
    assert manual_result["ok"] is False
    assert manual_result["executed"] is False
    assert "no explicit tool_action" in manual_result["error"]

    preview = run_work_queue_item(project, task["id"])
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["tool_result"]["executed"] is False
    assert list_tasks(project)[1]["status"] == "pending"

    class Completed:
        returncode = 0
        stdout = "tool ok"
        stderr = ""

    def fake_run(*args, **kwargs):
        assert args[0][0] == "powershell"
        assert kwargs["check"] is False
        return Completed()

    monkeypatch.setattr("question_research_poc.tool_executor.subprocess.run", fake_run)
    executed = run_work_queue_item(project, task["id"], execute=True)

    assert executed["ok"] is True
    assert executed["executed"] is True
    assert executed["task"]["status"] == "done"
    result_path = Path(executed["tool_result"]["result_path"])
    assert result_path.exists()
    assert result_path.parent.parent.name == "tool-runs"
    assert Path(executed["tool_result"]["stdout_path"]).read_text(encoding="utf-8") == "tool ok"
    bridge = build_tool_bridge_status(project)
    assert any(run["tool"] == "video-knowledge-pipeline" and run["kind"] == "health" for run in bridge["recent_runs"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "run_work_queue_item" in tools
    assert call_mcp_tool("run_work_queue_item", {"root": str(project), "id": task["id"]})["dry_run"] is True
    assert cli_main(["run-work-queue-item", "--project", str(project), "--id", task["id"]]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True


def test_local_tool_health_dashboard_is_metadata_first(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "本地工具状态如何进入驾驶舱？")

    health = get_tool_health_dashboard()
    names = {tool["name"] for tool in health["tools"]}
    payload = _project_payload(project)

    assert health["schema"] == "question_research_local_tool_health.v1"
    assert health["mode"] == "metadata_only"
    assert {"ai-research-workflow", "web-content-fetcher", "video-knowledge-pipeline", "video-download-orchestrator"}.issubset(names)
    assert all("recommended_next_action" in tool for tool in health["tools"])
    assert "local_tools" in payload["dashboard"]
    assert payload["dashboard"]["local_tools"]["summary"]["total"] >= 4


def test_tool_bridge_status_summarizes_runs_inbox_and_review_queue(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "外部工具桥接状态如何展示？")
    add_inbox_item(project, kind="search_result", title="候选搜索结果", url="https://example.com/a", source_tool="ai-research-workflow")
    source = add_source(project, title="待审来源", url="https://example.com/b")
    claim = add_claim(project, text="桥接导入仍需人工审核")
    add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="候选证据")
    tool_runs = project / "tool-runs"
    fetched = project / "fetched-sources"
    tool_runs.mkdir()
    fetched.mkdir()
    run_path = tool_runs / "web-content-fetch-2026-06-09T00-00-00.json"
    run_path.write_text(
        json.dumps(
            {
                "source": "web-content-fetcher",
                "request": {"url": "https://example.com/b"},
                "result_path": str(fetched / "source.json"),
                "markdown_path": str(fetched / "source.md"),
                "candidate_evidence": [{"id": "candidate"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (fetched / "source.md").write_text("# fetched", encoding="utf-8")

    status = build_tool_bridge_status(project)

    assert status["schema"] == "question_research_tool_bridge_status.v1"
    assert status["mode"] == "read_only_controller_state"
    assert status["source_inbox"]["counts"]["candidate"] == 1
    assert status["review_queue"]["count"] >= 2
    assert status["recent_runs"][0]["tool"] == "web-content-fetcher"
    assert status["recent_runs"][0]["counts"]["candidate_evidence"] == 1
    assert status["fetched_sources"][0]["path"].endswith("source.md")
    assert any(tool["name"] == "web-content-fetcher" and tool["recent_run_count"] == 1 for tool in status["tools"])
    assert any("does not run" in item for item in status["operator_boundary"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "get_tool_bridge_status" in tools
    assert call_mcp_tool("get_tool_bridge_status", {"root": str(project)})["schema"] == "question_research_tool_bridge_status.v1"
    assert cli_main(["get-tool-bridge-status", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recent_runs"][0]["path"] == str(run_path)


def test_tool_bridge_status_marks_ai_research_unavailable_when_live_http_fails(tmp_path: Path, synthetic_tool_registry: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "搜索后端漂移时 cockpit 如何收口？")

    monkeypatch.setattr(
        "question_research_poc.tool_bridge_status.ai_research_status",
        lambda timeout_seconds=1: {
            "ok": False,
            "base_url": "http://127.0.0.1:9082",
            "error": "connection refused",
            "next_action": "ai-research-workflow 服务未启动或端口不可达。",
        },
    )

    status = build_tool_bridge_status(project)
    ai_row = next(tool for tool in status["tools"] if tool["name"] == "ai-research-workflow")

    assert ai_row["metadata_available"] is True
    assert ai_row["available"] is False
    assert ai_row["live_ok"] is False
    assert ai_row["status"] == "service_unreachable"
    assert ai_row["live_check"]["base_url"] == "http://127.0.0.1:9082"
    assert "端口不可达" in ai_row["recommended_next_action"]
    assert any("暂停依赖 9082/8928" in action for action in status["next_actions"])
    assert any("cached/local-only fallback" in action for action in status["next_actions"])


def test_bridge_runs_list_read_retry_and_interfaces(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "桥接运行如何追踪？")

    run = create_bridge_run(
        project,
        tool="web-content-fetcher",
        action="fetch_source_content",
        request={"url": "https://example.com"},
        command=["python", "-m", "web_content_fetcher", "fetch", "https://example.com"],
        status="failed",
        artifact_paths=[str(project / "fetched-sources" / "source.md")],
        error="timeout",
        recovery_hint="提高 timeout 或启用 browser 模式。",
        human_review_required=False,
    )

    listed = list_bridge_runs(project)
    assert listed["counts"]["failed"] == 1
    assert listed["runs"][0]["tool"] == "web-content-fetcher"
    assert listed["runs"][0]["kind"] == "fetch_source_content"
    assert read_bridge_run(project, run["id"])["run"]["error"] == "timeout"
    retry = retry_bridge_run_plan(project, run["id"])
    assert retry["execute"] is False
    assert retry["recovery_hint"]

    assert "list_bridge_runs" in {tool["name"] for tool in list_mcp_tools()}
    assert call_mcp_tool("list_bridge_runs", {"root": str(project)})["counts"]["failed"] == 1
    assert cli_main(["list-bridge-runs", "--project", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs"][0]["id"] == run["id"]


def test_bridge_action_dry_run_missing_args_and_interfaces(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "Bridge action 如何安全执行？")

    planned = plan_bridge_action(project, "video_check_artifacts", {"bundle_dir": str(tmp_path / "bundle")})
    assert planned["dry_run"] is True
    assert planned["executed"] is False
    assert planned["status"] == "planned"
    assert planned["bridge_run"]["status"] == "planned"

    missing = run_bridge_action(project, "video_plan", args={}, execute=True)
    assert missing["status"] == "needs_human"
    assert missing["executed"] is False
    assert "media_path" in missing["error"]
    assert list_bridge_runs(project)["counts"]["needs_human"] == 1

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"plan_bridge_action", "run_bridge_action", "enqueue_bridge_actions"}.issubset(tools)
    assert call_mcp_tool("plan_bridge_action", {"root": str(project), "action": "video_check_artifacts", "args": {"bundle_dir": str(tmp_path / "bundle")}})["dry_run"] is True

    assert cli_main(["plan-bridge-action", "--project", str(project), "--action", "video_check_artifacts", "--args-json", json.dumps({"bundle_dir": str(tmp_path / "bundle")})]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_bridge_action.v1"


def test_bridge_action_live_web_fetch_preserves_candidate_evidence(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "Bridge action 抓取网页后如何保留候选边界？")
    source = add_source(project, title="测试网页", url="https://example.com/article", quality="unknown")
    claim = add_claim(project, text="网页正文可以生成候选证据")

    def fake_fetch(url: str, **kwargs):
        return {
            "status": "ok",
            "requested_url": url,
            "final_url": url,
            "extractor": "fake",
            "transport": "test",
            "text": "网页正文可以生成候选证据，但需要人工审核。",
        }

    monkeypatch.setattr("question_research_poc.web_fetch_bridge._run_fetch_command", fake_fetch)

    result = run_bridge_action(
        project,
        "web_fetch_source",
        args={"source_id": source.id, "claim_id": claim.id, "create_candidate_evidence": True},
        execute=True,
    )

    assert result["ok"] is True
    assert result["status"] == "imported"
    assert result["imported_counts"]["evidence"] == 1
    assert result["bridge_run"]["action"] == "bridge_action:web_fetch_source"
    evidence = list_records(project, "evidence")
    assert evidence[0]["status"] == "candidate"
    assert evidence[0]["confidence"] == "low"
    assert evidence[0]["relation"] == "unknown"


def test_bridge_action_ai_import_preserves_source_tool_and_candidate(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "AI 搜索结果如何导入？")
    result_path = tmp_path / "ai-result.json"
    result_path.write_text(
        json.dumps(
            {
                "sources": [{"title": "来源 A", "url": "https://example.com/a"}],
                "claims": [{"text": "主张 A"}],
                "evidence": [{"claim": "主张 A", "url": "https://example.com/a", "quote": "证据 A", "confidence": "low"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_bridge_action(project, "ai_research_import_json", args={"path": str(result_path)}, execute=True)

    assert result["status"] == "imported"
    assert result["imported_counts"] == {"sources": 1, "claims": 1, "evidence": 1}
    import_payload = json.loads(Path(result["result"]["import_path"]).read_text(encoding="utf-8"))
    assert import_payload["source_tool"] == "ai-research-workflow"
    assert import_payload["candidate"] is True
    assert list_records(project, "evidence")[0]["status"] == "candidate"


def test_vane_perplexica_import_creates_candidate_sources_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "Vane/Perplexica 如何作为候选搜索？")
    payload = {
        "message": "候选回答，只能作为上下文。",
        "sources": [
            {"content": "候选片段 A", "metadata": {"title": "来源 A", "url": "https://example.com/a"}},
            {"content": "候选片段 B", "metadata": {"title": "来源 B", "url": "https://example.com/b"}},
        ],
    }

    result = import_vane_perplexica_result(project, payload, raw_response_path="tool-runs/raw.json")

    assert result["counts"] == {"sources": 2, "claims": 0, "evidence": 0}
    assert len(list_records(project, "sources")) == 2
    assert list_records(project, "sources")[0]["quality"] == "unknown"
    assert "No verified evidence" in list_records(project, "sources")[0]["notes"]
    assert list_records(project, "evidence") == []
    import_payload = json.loads(Path(result["import_path"]).read_text(encoding="utf-8"))
    assert import_payload["source_tool"] == "vane-perplexica"
    assert import_payload["candidate"] is True


def test_vane_perplexica_bridge_action_and_interfaces(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "Vane/Perplexica bridge action 是否可用？")
    providers = {
        "providers": [
            {
                "id": "provider-1",
                "chatModels": [{"key": "chat-a"}],
                "embeddingModels": [{"key": "embed-a"}],
            }
        ]
    }
    response = {
        "message": "候选上下文",
        "sources": [{"content": "候选片段", "metadata": {"title": "候选来源", "url": "https://example.com/vane"}}],
    }
    monkeypatch.setattr("question_research_poc.vane_perplexica_bridge._get_json", lambda *args, **kwargs: providers)
    monkeypatch.setattr("question_research_poc.vane_perplexica_bridge._post_json", lambda *args, **kwargs: response)

    planned = plan_vane_perplexica_search(project, query="候选搜索", base_url="http://127.0.0.1:3000")
    assert planned["ok"] is True
    assert planned["payload"]["chatModel"] == {"providerId": "provider-1", "key": "chat-a"}

    result = run_bridge_action(
        project,
        "vane_perplexica_search",
        args={"query": "候选搜索", "base_url": "http://127.0.0.1:3000", "import_results": True},
        execute=True,
    )

    assert result["status"] == "imported"
    assert result["imported_counts"] == {"sources": 1, "claims": 0, "evidence": 0}
    assert result["human_review_required"] is True
    assert result["artifact_paths"]
    assert list_records(project, "sources")[0]["quality"] == "unknown"
    assert list_records(project, "evidence") == []

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"vane_perplexica_status", "plan_vane_perplexica_search", "run_vane_perplexica_search", "import_vane_perplexica_result"}.issubset(tools)
    assert call_mcp_tool("plan_vane_perplexica_search", {"root": str(project), "query": "候选搜索"})["ok"] is True

    assert cli_main(["plan-vane-perplexica-search", "--project", str(project), "--query", "候选搜索"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "vane-perplexica"


def test_external_researcher_manual_web_deep_research_flow(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "什么工具适合 AI 聚合对话深度研究？")

    plan = plan_external_researcher_session(
        project,
        clarification_answers="目标：先跑通网页端外部研究员；输出中文 Markdown。",
        providers="ChatGPT Deep Research, Gemini Deep Research",
        source_policy="优先官方文档和开源项目源码。",
    )

    assert plan["ok"] is True
    assert "请使用你的深度研究/深度搜索模式" in plan["deep_research_prompt"]
    assert Path(plan["markdown_path"]).exists()
    assert plan["bridge_run"]["tool"] == "external-researcher"
    assert plan["bridge_run"]["human_review_required"] is True

    auto_followup = answer_external_researcher_followup(project, followup_question="需要限制地域吗？")
    assert auto_followup["answer_source"] == "auto_default"
    assert "按原始研究问题继续推进" in auto_followup["answer"]

    manual_followup = answer_external_researcher_followup(project, followup_question="需要哪些工具？", manual_answer="只看开源和本地可控工具。")
    assert manual_followup["answer_source"] == "manual"
    assert manual_followup["answer"] == "只看开源和本地可控工具。"

    first = import_external_researcher_report(
        project,
        provider="ChatGPT Deep Research",
        report_text="ChatGPT 报告：建议使用 LangGraph 和本地证据账本。",
        prompt_text=plan["deep_research_prompt"],
    )
    second = import_external_researcher_report(
        project,
        provider="Gemini Deep Research",
        report_text="Gemini 报告：建议先做人工可控的外部研究员工作台。",
        prompt_text=plan["deep_research_prompt"],
    )

    assert first["counts"]["sources"] == 1
    assert second["counts"]["sources"] == 1
    assert len(list_records(project, "sources")) == 2
    assert list_records(project, "sources")[0]["quality"] == "unknown"
    assert list_external_researcher_reports(project)["count"] == 2

    bundle = export_external_researcher_bundle(project)
    aggregate = Path(bundle["markdown_path"]).read_text(encoding="utf-8")
    assert "ChatGPT Deep Research" in aggregate
    assert "Gemini Deep Research" in aggregate
    assert "Synthesis Prompt" in aggregate

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"plan_external_researcher_session", "answer_external_researcher_followup", "import_external_researcher_report", "export_external_researcher_bundle"}.issubset(tools)
    mcp_result = call_mcp_tool("list_external_researcher_reports", {"root": str(project)})
    assert mcp_result["count"] == 2

    assert cli_main(["plan-external-researcher", "--project", str(project), "--providers", "ChatGPT Deep Research"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_external_researcher.v1"


def test_external_researcher_autosave_drafts_are_exportable_without_duplicates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "复制粘贴回答如何防丢？")

    draft = save_external_researcher_report_draft(
        project,
        provider="ChatGPT",
        report_text="第一版草稿",
        prompt_text="统一提示词",
    )
    updated = save_external_researcher_report_draft(
        project,
        provider="ChatGPT",
        report_text="第二版草稿",
        prompt_text="统一提示词",
    )

    assert draft["draft"] is True
    assert Path(updated["markdown_path"]).exists()
    reports = list_external_researcher_reports(project)
    assert reports["count"] == 1
    assert reports["reports"][0]["provider"] == "ChatGPT"
    assert reports["reports"][0]["report_text"] == "第二版草稿"
    assert reports["reports"][0]["draft"] is True

    bundle = export_external_researcher_bundle(project)
    aggregate = Path(bundle["markdown_path"]).read_text(encoding="utf-8")
    assert bundle["report_count"] == 1
    assert "第二版草稿" in aggregate


def test_external_researcher_reports_are_scoped_to_current_project_question(tmp_path: Path) -> None:
    project = tmp_path / "project"
    first_project = init_project(project, "第一个研究问题")
    report = import_external_researcher_report(
        project,
        provider="ChatGPT",
        report_text="第一个问题的回答",
        import_as_source=False,
    )
    draft = save_external_researcher_report_draft(
        project,
        provider="Gemini",
        report_text="第一个问题的草稿",
    )

    assert report["project_id"] == first_project.id
    assert draft["project_id"] == first_project.id
    assert list_external_researcher_reports(project)["count"] == 2

    second_project = init_project(project, "第二个研究问题")
    scoped = list_external_researcher_reports(project)
    legacy = list_external_researcher_reports(project, include_legacy=True)

    assert second_project.id != first_project.id
    assert scoped["count"] == 0
    assert legacy["count"] == 0

    second_report = import_external_researcher_report(
        project,
        provider="Claude",
        report_text="第二个问题的回答",
        import_as_source=False,
    )
    reports = list_external_researcher_reports(project)
    assert second_report["project_id"] == second_project.id
    assert reports["count"] == 1
    assert reports["reports"][0]["provider"] == "Claude"
    assert reports["reports"][0]["question"] == "第二个研究问题"


def test_external_researcher_report_listing_tolerates_bad_utf8(tmp_path: Path) -> None:
    project = tmp_path / "project"
    current = init_project(project, "保存时遇到旧报告坏字节怎么办？")
    bad_report = project / "tool-runs" / "external-researcher-report-bad-utf8.json"
    bad_report.parent.mkdir(parents=True, exist_ok=True)
    bad_report.write_bytes(
        (
            '{"project_id":"'
            + current.id
            + '","provider":"Tencent Yuanbao","report_text":"bad byte: \x9a","created_at":"2026-06-20T08:00:00Z"}'
        ).encode("latin-1")
    )

    reports = list_external_researcher_reports(project)

    assert reports["count"] == 1
    assert reports["reports"][0]["provider"] == "Tencent Yuanbao"
    assert "bad byte" in reports["reports"][0]["report_text"]


def test_external_researcher_bridge_actions_manifest_and_runbook(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "外部深度研究如何进入候选审核？")
    report_path = project / "external-researcher-inbox" / "external-researcher-report-chatgpt.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("外部研究报告：这些内容只能作为候选上下文。", encoding="utf-8")

    planned = plan_bridge_action(project, "external_researcher_plan", {})
    assert planned["status"] == "planned"
    assert planned["dry_run"] is True
    assert planned["human_review_required"] is True
    assert planned["result"]["plan"]["bridge_run"]["tool"] == "external-researcher"

    missing = run_bridge_action(project, "external_researcher_import_report", args={"provider": "ChatGPT Deep Research"}, execute=True)
    assert missing["status"] == "needs_human"
    assert "report_text_or_path" in missing["error"]

    imported = run_bridge_action(
        project,
        "external_researcher_import_report",
        args={"provider": "ChatGPT Deep Research", "path": str(report_path)},
        execute=True,
    )
    assert imported["status"] == "imported"
    assert imported["imported_counts"] == {"sources": 1, "claims": 0, "evidence": 0}
    assert imported["human_review_required"] is True
    sources = list_records(project, "sources")
    assert sources[0]["source_type"] == "external_research_report"
    assert sources[0]["quality"] == "unknown"
    assert list_records(project, "evidence") == []

    runbook = build_agent_runbook(project)
    actions = [command.get("tool_action", {}).get("action") for command in runbook["commands"]]
    assert "external_researcher_import_report" in actions

    queued = enqueue_bridge_actions(project)
    queued_actions = [task.get("tool_action", {}).get("action") for task in queued["added"]]
    assert "external_researcher_import_report" in queued_actions

    manifest = build_agent_manifest(project)
    action_ids = {action["id"] for action in manifest["ui_actions"]}
    assert {"external_researcher_plan", "external_researcher_import", "external_researcher_export", "external_researcher_automation_plan", "external_researcher_login_profiles", "external_researcher_automation_check"}.issubset(action_ids)
    assert any("Deep Research provider reports" in item for item in manifest["forbidden_operations"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"plan_bridge_action", "run_bridge_action", "plan_external_researcher_session", "import_external_researcher_report"}.issubset(tools)
    assert call_mcp_tool("plan_bridge_action", {"root": str(project), "action": "external_researcher_automation_plan", "args": {"providers": "ChatGPT Deep Research"}})["dry_run"] is True

    assert cli_main(["run-bridge-action", "--project", str(project), "--action", "external_researcher_export_bundle", "--execute"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["human_review_required"] is True


def test_external_researcher_browser_automation_plan_is_executable_contract(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "网页端深度研究如何自动化成外部研究员？")

    template = write_external_researcher_profile_template(project)
    assert Path(template["path"]).exists()

    plan = plan_external_researcher_automation(
        project,
        clarification_answers="除澄清和追问外，其余动作都应由软件完成。",
        providers="ChatGPT Deep Research, Gemini Deep Research",
        profile_config_path=template["path"],
        followup_wait_seconds=10,
        max_wait_seconds=120,
    )
    assert plan["ok"] is True
    assert plan["kind"] == "automation_plan"
    assert plan["provider_profiles"][0]["url"].startswith("https://")
    assert plan["provider_profiles"][0]["user_data_dir"]
    assert ".local" in plan["provider_profiles"][0]["user_data_dir"]
    assert plan["persistent_profile_root"].endswith("external-researcher")
    assert "Playwright" not in plan["operator_boundary"][0]
    assert Path(plan["json_path"]).exists()

    dry_run = run_external_researcher_automation(project, automation_plan=plan["json_path"], dry_run=True)
    assert dry_run["ok"] is True
    assert dry_run["dry_run"] is True
    assert dry_run["plan"]["kind"] == "automation_plan"

    preflight = check_external_researcher_automation_profiles(project, automation_plan=plan["json_path"])
    assert preflight["ok"] is True
    assert preflight["kind"] == "automation_preflight"
    assert preflight["live"] is False
    assert preflight["blocking_count"] == 0
    assert all(row["status"] == "configured" for row in preflight["results"])

    login_prep = prepare_external_researcher_login_profiles(project, automation_plan=plan["json_path"], keep_open_seconds=30)
    assert login_prep["ok"] is True
    assert login_prep["kind"] == "login_profile_prep"
    assert login_prep["live"] is False
    assert all(row["status"] == "planned" for row in login_prep["results"])

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"plan_external_researcher_automation", "run_external_researcher_automation", "check_external_researcher_automation_profiles", "prepare_external_researcher_login_profiles", "write_external_researcher_profile_template"}.issubset(tools)
    mcp_plan = call_mcp_tool("plan_external_researcher_automation", {"root": str(project), "providers": "ChatGPT Deep Research"})
    assert mcp_plan["kind"] == "automation_plan"
    mcp_check = call_mcp_tool("check_external_researcher_automation_profiles", {"root": str(project), "automation_plan": plan["json_path"]})
    assert mcp_check["kind"] == "automation_preflight"
    mcp_login = call_mcp_tool("prepare_external_researcher_login_profiles", {"root": str(project), "automation_plan": plan["json_path"], "keep_open_seconds": 30})
    assert mcp_login["kind"] == "login_profile_prep"

    assert cli_main(["plan-external-researcher-automation", "--project", str(project), "--providers", "ChatGPT Deep Research", "--max-wait-seconds", "60"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "automation_plan"

    assert cli_main(["check-external-researcher-automation", "--project", str(project), "--automation-plan", plan["json_path"]]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "automation_preflight"

    assert cli_main(["prepare-external-researcher-login-profiles", "--project", str(project), "--automation-plan", plan["json_path"], "--keep-open-seconds", "30"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "login_profile_prep"

    assert cli_main(["run-external-researcher-automation", "--project", str(project), "--automation-plan", plan["json_path"], "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True


def test_external_researcher_default_provider_queue_matches_user_quota_boundary(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "默认应该调用哪些网页端深度研究？")

    plan = plan_external_researcher_automation(project)
    providers = plan["providers"]
    provider_keys = {profile["key"] for profile in plan["provider_profiles"]}

    assert providers == [
        "豆包深入研究",
        "通义千问研究",
    ]
    assert {"doubao", "qwen"} == provider_keys
    assert all(profile["enabled"] for profile in plan["provider_profiles"])
    urls = {profile["key"]: profile["url"] for profile in plan["provider_profiles"]}
    assert urls["qwen"] == "https://www.qianwen.com/?ch=tongyi_redirect"
    assert urls["doubao"] == "https://www.doubao.com/chat/"


def test_external_researcher_explicit_provider_urls_track_live_entrypoints(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "显式选择的问题入口应该打开哪里？")

    plan = plan_external_researcher_automation(
        project,
        providers="ChatGPT Deep Research, Gemini Deep Research, 智谱清言研究报告, MiniMax Deep Research, 阶跃AI / StepFun 深度研究",
    )
    urls = {profile["key"]: profile["url"] for profile in plan["provider_profiles"]}

    assert urls["chatgpt"] == "https://chatgpt.com/"
    assert urls["gemini"] == "https://gemini.google.com/app"
    assert urls["stepfun"] == "https://chat.stepfun.com/chats/new"
    assert urls["zhipu"] == "https://chatglm.cn/main/alltoolsdetail?lang=zh"
    assert urls["minimax"] == "https://agent.minimaxi.com/"


def test_external_researcher_browser_proxy_is_scoped_to_proxy_bound_providers(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "哪些网页端需要浏览器代理？")
    previous = os.environ.get("QUESTION_RESEARCH_BROWSER_PROXY")
    os.environ["QUESTION_RESEARCH_BROWSER_PROXY"] = "http://127.0.0.1:10808"
    try:
        plan = plan_external_researcher_automation(
            project,
            providers="ChatGPT Deep Research, Gemini Deep Research, MiniMax Deep Research, 豆包深入研究, 通义千问研究",
        )
    finally:
        if previous is None:
            os.environ.pop("QUESTION_RESEARCH_BROWSER_PROXY", None)
        else:
            os.environ["QUESTION_RESEARCH_BROWSER_PROXY"] = previous
    proxies = {profile["key"]: profile.get("proxy_server", "") for profile in plan["provider_profiles"]}

    assert proxies["chatgpt"] == "http://127.0.0.1:10808"
    assert proxies["gemini"] == "http://127.0.0.1:10808"
    assert proxies["minimax"] == "http://127.0.0.1:10808"
    assert proxies["doubao"] == ""
    assert proxies["qwen"] == ""


def test_omnigent_external_research_poc_spec_inbox_and_runner(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "把网页端深度研究做成外部研究员 PoC")

    result = run_omnigent_external_research_poc(
        project,
        clarification_answers="先在同一界面澄清问题，再委派网页端深度研究。",
        providers="ChatGPT Deep Research, Gemini Deep Research",
        source_policy="优先官方文档、开源源码和可复现实测。",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["schema"] == "question_research_omnigent_poc.v1"
    assert result["kind"] == "external_research_orchestration"
    assert result["dry_run"] is True
    assert result["bridge_run"]["tool"] == "omnigent-poc"
    assert result["bridge_run"]["human_review_required"] is True
    assert result["bridge_run"]["imported_counts"] == {"sources": 0, "claims": 0, "evidence": 0}

    spec_text = Path(result["agent_spec_path"]).read_text(encoding="utf-8")
    assert "external_deep_research_orchestrator" in spec_text
    assert "sys_read_inbox" in spec_text
    assert "elicitation" in spec_text
    assert "run_external_researcher_automation" in spec_text
    assert "ChatGPT Deep Research" in spec_text

    inbox_rows = [json.loads(line) for line in Path(result["inbox_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {row["kind"] for row in inbox_rows} >= {"clarification_completed", "provider_worker_planned", "human_followup_gate_ready", "automation_run_finished"}
    assert any(row.get("provider") == "Gemini Deep Research" for row in inbox_rows)
    assert Path(result["aggregate_markdown_path"]).exists()
    assert Path(result["markdown_path"]).exists()

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "run_omnigent_external_research_poc" in tools
    mcp_result = call_mcp_tool("run_omnigent_external_research_poc", {"root": str(project), "providers": "ChatGPT Deep Research", "dry_run": True})
    assert mcp_result["dry_run"] is True
    assert Path(mcp_result["agent_spec_path"]).exists()

    assert cli_main(["run-omnigent-external-research-poc", "--project", str(project), "--providers", "ChatGPT Deep Research"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_omnigent_poc.v1"

    manifest = build_agent_manifest(project)
    action_ids = {action["id"] for action in manifest["ui_actions"]}
    assert "omnigent_external_research_poc" in action_ids


def test_work_queue_executes_bridge_action_and_links_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    bundle = tmp_path / "video-run" / "webui-bundle"
    exports = tmp_path / "video-run" / "exports"
    bundle.mkdir(parents=True)
    exports.mkdir(parents=True)
    (bundle / "review.html").write_text("<html>review</html>", encoding="utf-8")
    (exports / "knowledge-note.md").write_text("# note", encoding="utf-8")
    (exports / "full-transcript.md").write_text("transcript", encoding="utf-8")
    init_project(project, "队列如何执行 bridge action？")
    task = enqueue_task(
        project,
        kind="bridge_action",
        title="检查视频 bundle",
        tool_action={"kind": "bridge_action", "action": "video_check_artifacts", "args": {"bundle_dir": str(bundle)}},
    )

    preview = run_work_queue_item(project, task["id"])
    assert preview["dry_run"] is True
    assert preview["tool_result"]["status"] == "planned"
    assert list_tasks(project)[0]["status"] == "pending"

    executed = run_work_queue_item(project, task["id"], execute=True)
    assert executed["ok"] is True
    assert executed["task"]["status"] == "done"
    assert executed["task"]["bridge_run_id"]
    assert executed["task"]["artifact_paths"]


def test_ai_research_failure_records_bridge_run(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "搜索失败怎么恢复？")

    def fake_post_json(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("question_research_poc.ai_research_bridge._post_json", fake_post_json)
    result = run_ai_research_search(project, base_url="http://127.0.0.1:9999")

    assert result["ok"] is False
    assert result["bridge_run"]["status"] == "failed"
    assert "服务未启动" in result["bridge_run"]["recovery_hint"]
    runs = list_bridge_runs(project, tool="ai-research-workflow")
    assert runs["counts"]["failed"] == 1


def test_ai_research_agent_research_records_job_trace(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "agent contract 如何验收？")

    def fake_post_json(url, payload, *, timeout):
        assert url == "http://127.0.0.1:9082/v1/agent/research"
        assert payload["auto_verify"] is False
        return {
            "job_id": "job_smoke",
            "status": "queued",
            "links": {
                "job": "http://127.0.0.1:9082/v1/agent/jobs/job_smoke",
                "events": "http://127.0.0.1:9082/v1/agent/jobs/job_smoke/events",
            },
        }

    def fake_get_json(url, *, timeout):
        if url.endswith("/events"):
            return {"events": [{"event": "completed"}]}
        return {
            "job_id": "job_smoke",
            "status": "succeeded",
            "result": {"run_id": "search_smoke", "sources": [], "claims": [], "evidence": []},
        }

    monkeypatch.setattr("question_research_poc.ai_research_bridge._post_json", fake_post_json)
    monkeypatch.setattr("question_research_poc.ai_research_bridge._get_json", fake_get_json)

    result = run_ai_research_agent_research(project, base_url="http://127.0.0.1:9082", no_network=True)

    assert result["ok"] is True
    assert result["endpoint"] == "/v1/agent/research"
    assert result["job_id"] == "job_smoke"
    assert result["run_id"] == "search_smoke"
    assert result["fallback_used"] is False
    assert result["failure_reason"] == ""
    assert result["bridge_run"]["action"] == "deep_research_agent_contract"
    runs = list_bridge_runs(project, tool="ai-research-workflow")
    assert runs["counts"]["succeeded"] == 1


def test_ai_research_agent_research_imports_run_report_payload(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "agent report 如何回填候选证据？")
    posted_payloads = []

    def fake_post_json(url, payload, *, timeout):
        assert url == "http://127.0.0.1:9082/v1/agent/research"
        posted_payloads.append(payload)
        return {
            "job_id": "job_report",
            "status": "queued",
            "links": {
                "job": "http://127.0.0.1:9082/v1/agent/jobs/job_report",
                "events": "http://127.0.0.1:9082/v1/agent/jobs/job_report/events",
            },
        }

    def fake_get_json(url, *, timeout):
        if url.endswith("/events"):
            return {"events": [{"event": "completed"}]}
        if url.endswith("/v1/runs/search_report/report.json"):
            return {
                "sources": [
                    {
                        "id": "src_remote",
                        "title": "Official report source",
                        "url": "https://example.com/official",
                        "source_type": "official",
                        "quality_score": 84,
                    }
                ],
                "claim_table": [
                    {
                        "id": "claim_remote",
                        "text": "官方报告包含可导入的候选证据。",
                        "verdict": "supported",
                        "confidence": 0.8,
                        "evidence_ids": ["ev_remote"],
                    }
                ],
                "evidence": [
                    {
                        "id": "ev_remote",
                        "source_id": "src_remote",
                        "quote_or_paraphrase": "The official report includes candidate evidence that should remain unreviewed.",
                        "support_direction": "supported",
                        "confidence": 0.8,
                    }
                ],
            }
        return {
            "job_id": "job_report",
            "status": "succeeded",
            "result": {"run_id": "search_report", "source_count": 1, "claim_count": 1, "evidence_count": 1},
        }

    monkeypatch.setattr("question_research_poc.ai_research_bridge._post_json", fake_post_json)
    monkeypatch.setattr("question_research_poc.ai_research_bridge._get_json", fake_get_json)

    result = run_ai_research_agent_research(project, base_url="http://127.0.0.1:9082", import_results=True, auto_verify=True)

    assert posted_payloads[0]["auto_verify"] is True
    assert result["ok"] is True
    assert result["run_id"] == "search_report"
    assert result["report_fetch_error"] == ""
    assert result["report_json"]["sources"][0]["id"] == "src_remote"
    assert result["imported"]["counts"] == {"sources": 1, "claims": 1, "evidence": 1}
    sources = list_records(project, "sources")
    claims = list_records(project, "claims")
    evidence = list_records(project, "evidence")
    assert sources[0]["quality"] == "good"
    assert claims[0]["text"] == "官方报告包含可导入的候选证据。"
    assert evidence[0]["claim_id"] == claims[0]["id"]
    assert evidence[0]["source_id"] == sources[0]["id"]
    assert evidence[0]["relation"] == "supports"
    assert evidence[0]["status"] == "candidate"
    assert result["bridge_run"]["status"] == "imported"
    assert result["bridge_run"]["imported_counts"] == {"sources": 1, "claims": 1, "evidence": 1}


def test_research_gap_analyzer_classifies_search_and_review_gaps(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "某产品当前是否仍可售并且资质有效？")
    source = add_source(project, title="二手解读", url="https://example.com/post", quality="unknown")
    supported = add_claim(project, text="该产品仍可售", notes="risk_level: high\nverdict: supported")
    add_evidence(project, claim_id=supported.id, source_id=source.id, quote_or_note="短证据", relation="supports")
    add_claim(project, text="该资质仍有效", notes="verdict: not_found")

    result = analyze_research_gaps(project, max_queries_per_round=4)
    gap_types = {gap["type"] for gap in result["gaps"]}
    statuses = {gap["status"] for gap in result["gaps"]}

    assert result["schema"] == "question_research_gap_analysis.v1"
    assert "claim_gap" in gap_types
    assert "evidence_gap" in gap_types
    assert "counter_evidence_gap" in gap_types
    assert "freshness_gap" in gap_types
    assert "review_gap" in gap_types
    assert "actionable_search" in statuses
    assert "needs_review" in statuses
    assert result["actionable_queries"]
    assert result["human_review_required"] is True


def test_research_gap_planner_dedupes_and_limits_queries() -> None:
    gaps = [
        {"id": "g1", "type": "claim_gap", "priority": "P1", "status": "actionable_search", "title": "A", "suggested_queries": ["same query", "same query", "second query"]},
        {"id": "g2", "type": "freshness_gap", "priority": "P0", "status": "actionable_search", "title": "B", "suggested_queries": ["fresh query"]},
        {"id": "g3", "type": "review_gap", "priority": "P2", "status": "needs_review", "title": "C", "suggested_queries": ["ignore me"]},
    ]

    planned = plan_followup_queries(gaps, max_queries=2)

    assert [item["query"] for item in planned] == ["fresh query", "same query"]
    assert {item["gap_id"] for item in planned} == {"g1", "g2"}


def test_research_loop_reports_bridge_down_without_fallback(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "bridge down 时不要伪造多轮研究")
    monkeypatch.setattr(
        "question_research_poc.research_loop.ai_research_status",
        lambda *args, **kwargs: {
            "ok": False,
            "metadata_available": True,
            "live_ok": False,
            "available": False,
            "status": "service_unreachable",
            "base_url": "http://127.0.0.1:1",
            "error": "connection refused",
        },
    )

    result = run_research_loop(project, query="smoke", rounds=2, base_url="http://127.0.0.1:1")

    assert result["schema"] == "question_research_loop_run.v1"
    assert result["status"] == "blocked_bridge_down"
    assert result["stop_reason"] == "bridge_down"
    assert result["job_id"] == ""
    assert result["run_id"] == ""
    assert result["fallback_used"] is False
    assert result["rounds"] == []
    assert all(Path(path).exists() for path in result["artifact_paths"])


def test_research_loop_runs_two_round_candidate_smoke(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "SearXNG local smoke 是否能多轮追缺口？")
    calls: list[str] = []

    monkeypatch.setattr(
        "question_research_poc.research_loop.ai_research_status",
        lambda *args, **kwargs: {
            "ok": True,
            "metadata_available": True,
            "live_ok": True,
            "available": True,
            "status": "available",
            "base_url": "http://127.0.0.1:9082",
        },
    )

    def fake_run(root, **kwargs):
        calls.append(str(kwargs.get("query")))
        index = len(calls)
        return {
            "ok": True,
            "job_id": f"job_{index}",
            "run_id": f"run_{index}",
            "fallback_used": False,
            "failure_reason": "",
            "bridge_run": {"id": f"bridge_{index}", "imported_counts": {"sources": 0, "claims": 0, "evidence": 0}},
        }

    monkeypatch.setattr("question_research_poc.research_loop.run_ai_research_agent_research", fake_run)
    monkeypatch.setattr("question_research_poc.research_loop.fetch_ai_research_run_quality", lambda *args, **kwargs: {"overall": "ok", "claim_quality": []})
    monkeypatch.setattr("question_research_poc.research_loop.fetch_ai_research_deepen_suggestions", lambda *args, **kwargs: {"overall": "ok", "deepen_suggestions": []})

    result = run_research_loop(project, query="SearXNG local smoke", rounds=2, max_queries_per_round=1, no_network=True)

    assert result["status"] == "needs_more_manual_input"
    assert result["stop_reason"] == "no_actionable_search_gap"
    assert result["job_id"] == "job_2"
    assert result["run_id"] == "run_2"
    assert result["fallback_used"] is False
    assert len(result["rounds"]) == 2
    assert all(round_item["jobs"] for round_item in result["rounds"])
    assert all(Path(path).exists() for path in result["artifact_paths"])
    assert result["candidate_only"] is True
    assert result["verified_evidence_created"] is False
    assert result["review_gate_required"] is True
    assert list_records(project, "evidence") == []

    listed = list_research_loops(project)
    assert listed["schema"] == "question_research_loop_list.v1"
    assert listed["loops"][0]["id"] == result["id"]
    read_back = read_research_loop(project, result["id"])
    assert read_back["schema"] == "question_research_loop_run.v1"
    assert read_back["candidate_only"] is True
    exported = export_research_loop_review_pack(project, loop_id=result["id"])
    assert exported["schema"] == "question_research_loop_review_pack.v1"
    assert exported["candidate_only"] is True
    assert exported["verified_evidence_created"] is False
    assert all(Path(path).exists() for path in exported["files"].values())
    assert "candidate-only" in Path(exported["files"]["candidate_import_table"]).read_text(encoding="utf-8")


def test_research_loop_does_not_repeat_followup_queries(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "重复 query 不应被多轮执行")
    calls: list[str] = []

    monkeypatch.setattr(
        "question_research_poc.research_loop.ai_research_status",
        lambda *args, **kwargs: {
            "ok": True,
            "metadata_available": True,
            "live_ok": True,
            "available": True,
            "status": "available",
            "base_url": "http://127.0.0.1:9082",
        },
    )

    def fake_run(root, **kwargs):
        calls.append(str(kwargs.get("query")))
        return {
            "ok": True,
            "job_id": f"job_{len(calls)}",
            "run_id": f"run_{len(calls)}",
            "fallback_used": False,
            "failure_reason": "",
            "bridge_run": {"id": f"bridge_{len(calls)}", "imported_counts": {}},
        }

    def fake_analysis(*args, **kwargs):
        return {
            "gaps": [{"id": "gap_repeat", "type": "claim_gap", "status": "actionable_search", "priority": "P1"}],
            "actionable_queries": [{"query": "repeat me", "gap_id": "gap_repeat", "priority": "P1", "reason": "same"}],
        }

    monkeypatch.setattr("question_research_poc.research_loop.run_ai_research_agent_research", fake_run)
    monkeypatch.setattr("question_research_poc.research_loop.fetch_ai_research_run_quality", lambda *args, **kwargs: {"overall": "ok"})
    monkeypatch.setattr("question_research_poc.research_loop.fetch_ai_research_deepen_suggestions", lambda *args, **kwargs: {"overall": "ok", "deepen_suggestions": []})
    monkeypatch.setattr("question_research_poc.research_loop.analyze_research_gaps", fake_analysis)

    result = run_research_loop(project, query="initial", rounds=4, max_queries_per_round=1, no_network=True)

    assert calls == ["initial", "repeat me"]
    assert result["stop_reason"] == "no_actionable_search_gap"
    assert result["rounds"][-1]["next_queries"] == []


def test_work_queue_research_loop_action_is_dry_run_by_default_and_live_candidate_only(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "队列里的 research loop 如何保证人审？")

    monkeypatch.setattr(
        "question_research_poc.research_loop.ai_research_status",
        lambda *args, **kwargs: {
            "ok": True,
            "metadata_available": True,
            "live_ok": True,
            "available": True,
            "status": "available",
            "base_url": "http://127.0.0.1:9082",
        },
    )

    def fake_run(root, **kwargs):
        return {
            "ok": True,
            "job_id": "job_queue",
            "run_id": "run_queue",
            "fallback_used": False,
            "failure_reason": "",
            "bridge_run": {"id": "bridge_queue", "imported_counts": {"sources": 0, "claims": 0, "evidence": 0}},
        }

    monkeypatch.setattr("question_research_poc.research_loop.run_ai_research_agent_research", fake_run)
    monkeypatch.setattr("question_research_poc.research_loop.fetch_ai_research_run_quality", lambda *args, **kwargs: {"overall": "ok"})
    monkeypatch.setattr("question_research_poc.research_loop.fetch_ai_research_deepen_suggestions", lambda *args, **kwargs: {"overall": "ok", "deepen_suggestions": []})

    task = enqueue_task(
        project,
        kind="research_loop",
        title="Loop",
        tool_action={"kind": "research_loop", "args": {"query": "queue smoke", "rounds": 1, "max_queries_per_round": 1}},
    )

    preview = run_work_queue_item(project, task["id"])
    assert preview["tool_result"]["status"] == "planned"
    assert preview["tool_result"]["executed"] is False
    assert preview["tool_result"]["candidate_only"] is True

    executed = run_work_queue_item(project, task["id"], execute=True)
    assert executed["ok"] is True
    assert executed["tool_result"]["executed"] is True
    assert executed["tool_result"]["candidate_only"] is True
    assert executed["tool_result"]["verified_evidence_created"] is False
    assert executed["queue"]["tasks"][0]["status"] == "done"


def test_deep_research_cli_reports_agent_contract_success(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "deep research smoke 怎么验收？")

    monkeypatch.setattr(
        "question_research_poc.cli.ai_research_status",
        lambda *args, **kwargs: {
            "ok": True,
            "metadata_available": True,
            "live_ok": True,
            "available": True,
            "status": "available",
            "base_url": "http://127.0.0.1:9082",
            "error": "",
            "next_action": "",
        },
    )
    monkeypatch.setattr(
        "question_research_poc.cli.run_ai_research_agent_research",
        lambda *args, **kwargs: {
            "ok": True,
            "job_id": "job_smoke",
            "run_id": "search_smoke",
            "fallback_used": False,
            "failure_reason": "",
            "bridge_run": {"status": "succeeded"},
        },
    )

    assert cli_main(["deep-research", "--project", str(project), "--query", "SearXNG smoke", "--no-network"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_deep_research_run.v1"
    assert payload["live_ok"] is True
    assert payload["job_id"] == "job_smoke"
    assert payload["run_id"] == "search_smoke"
    assert payload["fallback_used"] is False
    assert payload["failure_reason"] == ""
    assert payload["ai_research_status"]["metadata_available"] is True
    assert payload["ai_research_status"]["status"] == "available"


def test_deep_research_cli_reports_bridge_down_without_fallback(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "bridge down 时要不要静默降级？")
    called = {"agent": False}

    monkeypatch.setattr(
        "question_research_poc.cli.ai_research_status",
        lambda *args, **kwargs: {
            "ok": False,
            "metadata_available": True,
            "live_ok": False,
            "available": False,
            "status": "service_unreachable",
            "base_url": "http://127.0.0.1:1",
            "error": "connection refused",
            "next_action": "Start ai-research-workflow and retry.",
        },
    )

    def fake_agent_run(*args, **kwargs):
        called["agent"] = True
        return {"ok": True}

    monkeypatch.setattr("question_research_poc.cli.run_ai_research_agent_research", fake_agent_run)

    assert cli_main(["deep-research", "--project", str(project), "--query", "SearXNG smoke", "--no-network"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["live_ok"] is False
    assert payload["available"] is False
    assert payload["status"] == "service_unreachable"
    assert payload["job_id"] == ""
    assert payload["run_id"] == ""
    assert payload["fallback_used"] is False
    assert payload["failure_reason"] == "bridge_down"
    assert "deep-research did not run" in payload["error"]
    assert called["agent"] is False


def test_deep_research_cli_requires_full_bridge_availability(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "metadata 缺失时 deep research 能不能跑？")
    called = {"agent": False}

    monkeypatch.setattr(
        "question_research_poc.cli.ai_research_status",
        lambda *args, **kwargs: {
            "ok": True,
            "metadata_available": False,
            "live_ok": True,
            "available": False,
            "status": "metadata_missing",
            "base_url": "http://127.0.0.1:9082",
            "error": "",
            "next_action": "Refresh local tool registry before retry.",
        },
    )

    def fake_agent_run(*args, **kwargs):
        called["agent"] = True
        return {"ok": True}

    monkeypatch.setattr("question_research_poc.cli.run_ai_research_agent_research", fake_agent_run)

    assert cli_main(["deep-research", "--project", str(project), "--query", "SearXNG smoke", "--no-network"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["live_ok"] is True
    assert payload["available"] is False
    assert payload["status"] == "metadata_missing"
    assert payload["ai_research_status"]["metadata_available"] is False
    assert payload["ai_research_status"]["live_ok"] is True
    assert payload["ai_research_status"]["available"] is False
    assert payload["failure_reason"] == "bridge_down"
    assert called["agent"] is False


def test_ai_research_url_discovery_prefers_registry_service_file(tmp_path: Path, monkeypatch) -> None:
    registry_service = tmp_path / "registry-service.json"
    legacy_service = tmp_path / "legacy-service.json"
    registry = tmp_path / "tool-registry.json"
    registry_service.write_text(json.dumps({"base_url": "http://127.0.0.1:9911"}, ensure_ascii=False), encoding="utf-8")
    legacy_service.write_text(json.dumps({"base_url": "http://127.0.0.1:9912"}, ensure_ascii=False), encoding="utf-8")
    registry.write_text(
        json.dumps(
            {
                "tools": {
                    "ai-research-workflow": {
                        "path": str(tmp_path / "ai-research-workflow"),
                        "service_file": str(registry_service),
                        "http": {"fallback_base_url": "http://127.0.0.1:9913"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("question_research_poc.ai_research_bridge.REGISTRY_PATH", registry)
    monkeypatch.setattr("question_research_poc.ai_research_bridge.SERVICE_FILE", legacy_service)
    monkeypatch.delenv("AI_RESEARCH_WORKFLOW_URL", raising=False)

    assert resolve_ai_research_url() == "http://127.0.0.1:9911"

    registry_service.unlink()
    assert resolve_ai_research_url() == "http://127.0.0.1:9912"

    legacy_service.unlink()
    assert resolve_ai_research_url() == "http://127.0.0.1:9913"


def test_ai_research_search_plan_and_tool_exposure(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "如何调度外部搜索？")

    plan = plan_ai_research_search(project, mode="web", max_results=5, import_results=True, base_url="http://127.0.0.1:9999")

    assert plan["ok"] is True
    assert plan["tool"] == "ai-research-workflow"
    assert plan["base_url"] == "http://127.0.0.1:9999"
    assert plan["endpoint"] == "/v1/search"
    assert plan["payload"]["topic"] == "如何调度外部搜索？"
    assert plan["payload"]["max_results"] == 5
    assert plan["import_results"] is True
    assert "delegation_boundary" in plan
    assert "failure_next_action" in plan

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "plan_ai_research_search" in tools
    assert call_mcp_tool("plan_ai_research_search", {"root": str(project), "base_url": "http://127.0.0.1:9999"})["endpoint"] == "/v1/search"

    assert cli_main(["plan-ai-research-search", "--project", str(project), "--base-url", "http://127.0.0.1:9999"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "http://127.0.0.1:9999"


def test_web_fetch_plan_is_read_only_and_agent_visible(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    init_project(project, "如何抓取网页正文？")

    plan = plan_fetch_source_content(project, url="https://example.com/a", title="Example", create_candidate_evidence=True)

    assert plan["ok"] is True
    assert plan["tool"] == "web-content-fetcher"
    assert "web_content_fetcher" in " ".join(plan["command"])
    assert plan["url"] == "https://example.com/a"
    assert plan["outputs"]["markdown_path"].endswith(".md")
    assert plan["create_candidate_evidence"] is True
    assert list_records(project, "sources") == []

    missing = plan_fetch_source_content(project, source_id="missing_source")
    assert missing["ok"] is False
    assert missing["source"]["missing"] is True
    assert "failure_next_action" in missing

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "plan_fetch_source_content" in tools
    assert call_mcp_tool("plan_fetch_source_content", {"root": str(project), "url": "https://example.com/b"})["ok"] is True

    assert cli_main(["plan-fetch-source-content", "--project", str(project), "--url", "https://example.com/c"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["url"] == "https://example.com/c"


def test_web_ui_exposes_actionable_gate_next_steps() -> None:
    app_js = Path(__file__).resolve().parents[1] / "web" / "app.js"
    index_html = Path(__file__).resolve().parents[1] / "web" / "index.html"
    source = app_js.read_text(encoding="utf-8")
    html = index_html.read_text(encoding="utf-8")

    assert "function nextStepActionForGate" in source
    assert "function runNextStepAction" in source
    assert "function focusPanel" in source
    assert "function renderWorkflowArtifacts" in source
    assert "function renderGateDetails" in source
    assert "function renderReviewQueue" in source
    assert "function renderSourceInbox" in source
    assert "function loadSourceInbox" in source
    assert "function reviewNoteFor" in source
    assert "function renderDashboard" in source
    assert "function renderProjectOverview" in source
    assert "stageDetailSummary" in source
    assert "function renderAiResearchBridge" in source
    assert "function importAiResearchResultPath" in source
    assert "function renderWebFetchBridge" in source
    assert "function planVideoKnowledgeRun" in source
    assert "function importVideoKnowledgeArtifacts" in source
    assert "function renderVideoKnowledgeBridge" in source
    assert "function renderLocalToolAction" in source
    assert "function renderLocalToolActionMarkdown" in source
    assert "function renderToolBridgeStatus" in source
    assert "function loadToolBridgeStatus" in source
    assert "function loadBridgeRuns" in source
    assert "function renderBridgeRuns" in source
    assert "function renderBridgeAction" in source
    assert "function checkVideoRunArtifacts" in source
    assert "function renderCompletenessAudit" in source
    assert "function loadCompletenessAudit" in source
    assert "function renderResearchPackResult" in source
    assert "function renderFinalAnswerResult" in source
    assert "function renderKnowledgeBaseHandoffResult" in source
    assert "function renderWorkQueue" in source
    assert "function renderWorkQueueMarkdown" in source
    assert "function renderGraphCandidates" in source
    assert "function loadGraphCandidates" in source
    assert "function pasteProviderAnswerFromClipboard" in source
    assert "function archiveProviderClipboardAnswer" in source
    assert "function updateProviderPasteProgress" in source
    assert "function mergeArchivedProviderReports" in source
    assert "function renderDeepMergeResult" in source
    assert "function scheduleProviderDraftAutosave" in source
    assert "function autosaveProviderDraft" in source
    assert "function flushProviderDraftAutosaves" in source
    assert "function restoreProviderDrafts" in source
    assert "function currentProjectDraftScope" in source
    assert "function providerQuestionFingerprint" in source
    assert "function resetProviderPasteInbox" in source
    assert "function clearExternalResearcherInboxForNewQuestion" in source
    assert "function renderProviderPasteReports" in source
    assert "replace(/\\\\/g, \"/\").toLowerCase()" in source
    assert 'projectId || "uninitialized"' in source
    assert "resetProviderPasteInbox();" in source
    assert "旧问题回答不会自动带入" in source
    assert "await loadExternalReports();" in source
    assert "renderProviderPasteReports(payload);" in source
    assert "/api/external-researcher-report" in source
    assert "import_as_source: false" in source
    assert "window.localStorage.setItem" in source
    assert "navigator.clipboard.readText" in source
    assert "el.deepMergeWhenComplete.disabled = archived === 0" in source
    assert "至少先存档一份 AI 回答" in source
    assert "正在整合..." in source
    assert "Markdown:" in source
    assert "JSON:" in source
    assert "/api/agent-runbook" in source
    assert "/api/agent/manifest" in source
    assert "/api/local-tool-action" in source
    assert "/api/tool-bridge-status" in source
    assert "/api/bridge-runs" in source
    assert "/api/bridge-run" in source
    assert "/api/retry-bridge-run-plan" in source
    assert "/api/plan-bridge-action" in source
    assert "/api/run-bridge-action" in source
    assert "/api/enqueue-bridge-actions" in source
    assert "/api/check-video-run-artifacts" in source
    assert "/api/completeness-audit" in source
    assert "/api/cockpit-readiness" in source
    assert "/api/enqueue-runbook-tasks" in source
    assert "/api/work-queue" in source
    assert "/api/run-work-queue-item" in source
    assert "/api/graph-candidates" in source
    assert "/api/generate-graph-candidates" in source
    assert "/api/review-graph-candidate" in source
    assert "/api/export-reviewed-graph" in source
    assert "/api/source-inbox" in source
    assert "/api/source-inbox/add" in source
    assert "/api/export-research-pack" in source
    assert "/api/export-final-answer" in source
    assert "/api/export-research-pack-obsidian" in source
    assert "/api/create-logseq-review-handoff" in source
    assert 'data-next-step-action="${safe(action.id)}"' in source
    assert "data-gate-id" in source
    assert "data-queue-focus" in source
    assert "data-queue-claim-id" in source
    assert "queueClaimId" in source
    assert "data-inbox-import" in source
    assert "data-inbox-reject" in source
    assert "task_route_present" in source
    assert "sources_present" in source
    assert "source_quality_reviewed" in source
    assert "claims_present" in source
    assert "evidence_present" in source
    assert "verified_evidence_present" in source
    assert "multi_perspective_review_present" in source
    assert "reader_persona_review_present" in source
    assert "result_file_chain_complete" in source
    assert 'id="sourcesPanel"' in html
    assert 'id="claimsPanel"' in html
    assert 'id="evidencePanel"' in html
    assert 'id="workflowArtifactRows"' in html
    assert 'id="gateDetailRows"' in html
    assert 'id="reviewQueueRows"' in html
    assert 'id="reviewQueueWorkbench"' in html
    assert 'id="sourceInboxPanel"' in html
    assert 'id="sourceInboxRows"' in html
    assert 'id="addSourceInboxItemBtn"' in html
    assert 'id="refreshSourceInboxBtn"' in html
    assert "review-decision-note" in source
    assert "data-source-review-apply" in source
    assert "data-evidence-review-apply" in source
    assert "review-source" in source
    assert "review-evidence" in source
    assert 'id="dashboardPanel"' in html
    assert 'id="stageDetailSummary"' in html
    assert 'id="claimCoverage"' in html
    assert 'id="overviewClaimRows"' in html
    assert 'id="overviewArtifactRows"' in html
    assert 'id="completenessAuditPanel"' in html
    assert 'id="completenessAuditBtn"' in html
    assert 'id="completenessAuditRows"' in html
    assert 'id="cockpitReadinessBtn"' in html
    assert 'id="localToolHealthRows"' in html
    assert 'id="searchPlanBtn"' in html
    assert 'id="searchRunsBtn"' in html
    assert 'id="aiResearchResultPath"' in html
    assert 'id="importAiResearchResultBtn"' in html
    assert 'id="aiResearchBridgeSummary"' in html
    assert 'id="fetchPlanBtn"' in html
    assert 'id="fetchDirectUrl"' in html
    assert 'id="fetchUseBrowser"' in html
    assert 'id="fetchIncludeRaw"' in html
    assert 'id="webFetchBridgeSummary"' in html
    assert 'id="videoPlanBtn"' in html
    assert 'id="videoArtifactCheckBtn"' in html
    assert 'id="videoMediaPath"' in html
    assert 'id="videoWorkspace"' in html
    assert 'id="videoBundleDir"' in html
    assert 'id="videoImportBtn"' in html
    assert 'id="videoBridgeSummary"' in html
    assert 'id="localToolId"' in html
    assert 'id="localToolAction"' in html
    assert 'id="localToolDryRunBtn"' in html
    assert 'id="localToolActionRows"' in html
    assert 'id="refreshToolBridgeStatusBtn"' in html
    assert 'id="bridgeRunId"' in html
    assert 'id="readBridgeRunBtn"' in html
    assert 'id="retryBridgeRunBtn"' in html
    assert 'id="bridgeActionName"' in html
    assert 'id="bridgeActionArgs"' in html
    assert 'id="bridgeActionPlanBtn"' in html
    assert 'id="bridgeActionRunBtn"' in html
    assert 'id="enqueueBridgeActionsBtn"' in html
    assert "默认 dry-run" in html
    assert 'id="externalResearcherPanel"' in html
    assert 'id="aiDeepResearchLaunchPanel"' in html
    assert "AI 深研收件箱" in html
    assert 'id="deepResearchQuestionInput"' in html
    assert 'id="deepProviderGrid"' in html
    assert 'id="deepOpenLoginBtn"' in html
    assert 'id="deepRunAutomationBtn"' in html
    assert 'id="deepCopyPromptBtn"' in html
    assert 'id="deepManualReportProvider"' in html
    assert 'id="deepManualReportText"' in html
    assert 'id="deepImportManualReportBtn"' in html
    assert 'id="providerPasteGrid"' in html
    assert 'id="providerPasteProgress"' in html
    assert 'id="deepMergeWhenCompleteBtn"' in html
    assert 'id="deepMergeResult"' in html
    assert "AI 回答收件箱" in html
    assert "0 / 15 已存档" in html
    assert "整合已存档回答成 MD" in html
    assert "至少存档一份回答后即可汇总" in html
    assert "整合后会在这里显示 Markdown 文件路径" in html
    assert "自动保存" in source
    assert html.count("data-paste-provider=") == 15
    assert html.count("data-provider-report=") == 15
    assert html.count('class="provider-icon-btn"') == 15
    assert html.count('class="provider-brand-icon"') == 15
    assert html.count('class="provider-icon-fallback" hidden') == 15
    assert html.count("data-provider-icon=") == 15
    assert html.count('src="data:image/png;base64,') == 15
    assert 'aria-label="粘贴 ChatGPT 回答"' in html
    assert 'class="provider-icon-sprite"' not in html
    assert 'href="#provider-icon-' not in html
    assert '/assets/provider-icons/' not in html
    assert 'data-provider-icon="chatgpt"' in html
    assert 'data-provider-icon="claude"' in html
    assert 'data-provider-icon="gemini"' in html
    assert 'data-provider-icon="deepseek"' in html
    assert 'data-provider-icon="doubao"' in html
    assert 'data-provider-icon="qianwen"' in html
    assert 'data-provider-icon="kimi"' in html
    assert 'data-provider-icon="perplexity"' in html
    assert 'data-provider-icon="grok"' in html
    assert 'data-provider-icon="yuanbao"' in html
    assert 'data-provider-icon="metaso"' in html
    assert 'data-provider-icon="stepfun"' in html
    assert 'data-provider-icon="zhipu"' in html
    assert 'data-provider-icon="manus"' in html
    assert 'data-provider-icon="minimax"' in html
    assert 'data-paste-provider="ChatGPT"' in html
    assert 'data-paste-provider="Claude"' in html
    assert 'data-paste-provider="Gemini"' in html
    assert 'data-paste-provider="DeepSeek"' in html
    assert 'data-paste-provider="豆包"' in html
    assert 'data-paste-provider="千问"' in html
    assert 'data-paste-provider="Kimi"' in html
    assert 'data-paste-provider="Perplexity"' in html
    assert 'data-paste-provider="Grok"' in html
    assert 'data-paste-provider="腾讯元宝"' in html
    assert 'data-paste-provider="秘塔"' in html
    assert 'data-paste-provider="阶跃AI"' in html
    assert 'data-paste-provider="智谱清言"' in html
    assert 'data-paste-provider="Manus"' in html
    assert 'data-paste-provider="MiniMax"' in html
    assert "打开网页端" in html
    assert "copy prompt there" in html
    assert "https://chatgpt.com/" in html
    assert "https://claude.ai/new" in html
    assert "https://gemini.google.com/app" in html
    assert "https://chat.deepseek.com/" in html
    assert "https://kimi.moonshot.cn/" in html
    assert "https://www.perplexity.ai/" in html
    assert "https://grok.com/" in html
    assert "https://yuanbao.tencent.com/chat/naQivTmsDa" in html
    assert "https://metaso.cn/" in html
    assert "https://www.tongyi.com/" in html
    assert "https://www.stepfun.com/chats/new" in html
    assert "https://manus.im/" in html
    assert "https://agent.minimaxi.com/" in html
    assert "复制统一提示词" in html
    assert "AI 回答收件箱" in html
    assert "保存粘贴报告" in html
    assert "登录/诊断窗口" in html
    assert "可选自动跑豆包/千问" in html
    assert "主流程：生成提示词" in html
    assert ".local/browser-profiles/external-researcher" in html
    assert 'value="豆包深入研究" checked' in html
    assert 'value="通义千问研究" checked' in html
    assert 'id="externalProviders" value="豆包深入研究, 通义千问研究"' in html
    assert "ChatGPT Deep Research" in html
    assert "Google 登录拦截" in html
    assert "Gemini Deep Research" in html
    assert "已持久登录，可自动跑" in html
    assert "阶跃 AI / StepFun" in html
    assert "chat.stepfun.com" in html
    assert "滑块验证阻塞" in html
    assert "加载异常，先诊断" in html
    assert 'id="externalPlanBtn"' in html
    assert 'id="externalImportReportBtn"' in html
    assert 'id="externalExportBtn"' in html
    assert "<option>external_researcher_plan</option>" in html
    assert "<option>external_researcher_import_report</option>" in html
    assert "<option>external_researcher_automation_plan</option>" in html
    assert 'id="toolBridgeStatusRows"' in html
    assert 'id="exportResearchPackBtn"' in html
    assert 'id="exportFinalAnswerBtn"' in html
    assert 'id="exportObsidianPackBtn"' in html
    assert 'id="logseqHandoffBtn"' in html
    assert 'id="obsidianVault"' in html
    assert 'id="agentRunbookBtn"' in html
    assert 'id="agentManifestBtn"' in html
    assert 'id="enqueueRunbookTasksBtn"' in html
    assert 'id="refreshWorkQueueBtn"' in html
    assert 'id="workQueuePanel"' in html
    assert "data-workqueue-preview" in source
    assert "data-workqueue-execute" in source
    assert "data-graph-review" in source
    assert "data-graph-row" in source
    assert 'id="graphCandidatePanel"' in html
    assert 'id="graphCandidateRows"' in html
    assert 'id="generateGraphCandidatesBtn"' in html
    assert 'id="refreshGraphCandidatesBtn"' in html
    assert 'id="exportReviewedGraphBtn"' in html


def test_web_app_exposes_research_pack_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/export-research-pack"' in source
    assert "export_research_pack" in source


def test_web_app_serves_local_icon_assets() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert 'parsed.path.startswith("/assets/")' in source
    assert '"image/png"' in source
    assert '"image/svg+xml"' in source
    assert '"image/x-icon"' in source


def test_web_app_exposes_final_answer_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/export-final-answer"' in source
    assert "export_final_answer" in source


def test_web_app_exposes_project_overview_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/project-overview"' in source
    assert "build_project_overview" in source


def test_web_app_exposes_agent_manifest_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/agent/manifest"' in source
    assert "build_agent_manifest" in source


def test_web_app_exposes_explicit_review_api_aliases() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/review-source"' in source
    assert '"/api/review-evidence"' in source


def test_web_app_exposes_agent_runbook_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/agent-runbook"' in source
    assert "build_agent_runbook" in source


def test_web_app_exposes_knowledge_base_handoff_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/export-research-pack-obsidian"' in source
    assert '"/api/create-logseq-review-handoff"' in source
    assert "export_research_pack_to_obsidian" in source
    assert "create_logseq_review_handoff" in source


def test_web_app_exposes_work_queue_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/work-queue"' in source
    assert '"/api/enqueue-runbook-tasks"' in source
    assert '"/api/update-work-queue-item"' in source
    assert '"/api/run-work-queue-item"' in source
    assert "enqueue_runbook_tasks" in source
    assert "get_work_queue" in source
    assert "run_work_queue_item" in source


def test_web_app_exposes_local_tool_action_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/local-tool-action"' in source
    assert "run_local_tool_action" in source


def test_web_app_exposes_tool_bridge_status_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/tool-bridge-status"' in source
    assert "build_tool_bridge_status" in source


def test_tool_bridge_status_reports_backend_modes(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "后端可用性如何影响研究？")
    monkeypatch.setattr("question_research_poc.tool_bridge_status.ai_research_status", lambda **kwargs: {"ok": True, "base_url": "http://127.0.0.1:9082", "error": "", "next_action": ""})
    monkeypatch.setattr("question_research_poc.tool_bridge_status._tcp_service_check", lambda *args, **kwargs: {"ok": True, "base_url": "http://127.0.0.1:8928", "error": "", "recovery_hint": ""})

    full = build_tool_bridge_status(project)
    assert full["backend_mode"] == "full_research"
    assert "deep-research/search live actions" in full["fallback_scope"]

    monkeypatch.setattr("question_research_poc.tool_bridge_status._tcp_service_check", lambda *args, **kwargs: {"ok": False, "base_url": "http://127.0.0.1:8928", "error": "refused", "recovery_hint": "start searxng"})
    degraded = build_tool_bridge_status(project)
    assert degraded["backend_mode"] == "degraded_local_only"
    assert any("SearXNG" in item for item in degraded["next_actions"])


def test_bridge_action_blocks_ai_search_when_backend_unreachable(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "后端不可达时不要硬跑搜索")
    called = {"run": False}
    monkeypatch.setattr("question_research_poc.bridge_actions.ai_research_status", lambda *args, **kwargs: {"ok": False, "base_url": "http://127.0.0.1:1", "error": "refused", "next_action": "start service"})

    def fake_run(*args, **kwargs):
        called["run"] = True
        return {"ok": True}

    monkeypatch.setattr("question_research_poc.bridge_actions.run_ai_research_search", fake_run)
    result = run_bridge_action(project, "ai_research_search", args={"deep": True, "import_results": True}, execute=True)

    assert result["status"] == "needs_human"
    assert result["blocked_by_backend"] == "ai-research-workflow"
    assert "unreachable" in result["error"]
    assert called["run"] is False


def test_agent_runbook_does_not_enqueue_ai_search_when_backend_degraded(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    init_project(project, "需要更多来源吗？")
    monkeypatch.setattr(
        "question_research_poc.agent_runbook.build_tool_bridge_status",
        lambda *args, **kwargs: {"backend_mode": "degraded_local_only", "backend_summary": "ai-research down", "fallback_scope": ["cached artifacts"]},
    )

    runbook = build_agent_runbook(project)
    actions = [row.get("tool_action", {}).get("action") for row in runbook["commands"] if isinstance(row.get("tool_action"), dict)]
    titles = [row["title"] for row in runbook["commands"]]

    assert "ai_research_search" not in actions
    assert "Backend degraded: pause live AI research search" in titles


def test_audit_sync_safety_classifies_local_artifacts_and_interfaces(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert cli_main(["audit-sync-safety", "--repo", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_sync_safety.v1"
    assert payload["github_origin_advice"]["recommended_repo_name"] == "question-research-poc"
    assert call_mcp_tool("audit_sync_safety", {"repo": str(repo)})["schema"] == "question_research_sync_safety.v1"
    manifest = build_agent_manifest(str(repo))
    assert any(item["artifact"] == "sync_safety" for item in manifest["read_artifact_endpoints"])


def test_web_app_exposes_sync_safety_api_and_ui_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    web_app = (root / "src" / "question_research_poc" / "web_app.py").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "web" / "app.js").read_text(encoding="utf-8")

    assert '"/api/sync-safety"' in web_app
    assert "backendModeBanner" in html
    assert "syncSafetyBtn" in html
    assert "renderBackendMode" in app_js
    assert "renderSyncSafety" in app_js


def test_web_app_exposes_research_loop_api_and_ui_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    web_app = (root / "src" / "question_research_poc" / "web_app.py").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "web" / "app.js").read_text(encoding="utf-8")

    assert '"/api/analyze-research-gaps"' in web_app
    assert '"/api/research-loops"' in web_app
    assert '"/api/research-loop"' in web_app
    assert '"/api/export-research-loop-review-pack"' in web_app
    assert "研究缺口 / 循环研究" in html
    assert "researchGapAnalyzeBtn" in html
    assert "researchLoopRunBtn" in html
    assert "candidate-only" in html
    assert "renderResearchGapLoop" in app_js
    assert "renderResearchLoopList" in app_js
    assert "exportResearchLoopPack" in app_js


def test_mcp_and_manifest_expose_research_loop_read_interfaces(tmp_path: Path) -> None:
    tools = {tool["name"] for tool in list_mcp_tools()}
    assert {"list_research_loops", "read_research_loop", "export_research_loop_review_pack"}.issubset(tools)

    manifest = build_agent_manifest(str(tmp_path))
    artifacts = {item["artifact"]: item for item in manifest["read_artifact_endpoints"]}
    assert artifacts["research_loops"]["mcp"] == "list_research_loops"
    assert artifacts["research_loop_review_pack"]["api"] == "/api/export-research-loop-review-pack"
    assert any("analyze_research_gaps" in item for item in manifest["recommended_agent_flow"])


def test_web_app_exposes_bridge_run_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/bridge-runs"' in source
    assert '"/api/bridge-run"' in source
    assert '"/api/retry-bridge-run-plan"' in source
    assert '"/api/check-video-run-artifacts"' in source
    assert "list_bridge_runs" in source
    assert "read_bridge_run" in source
    assert "retry_bridge_run_plan" in source
    assert "check_video_run_artifacts" in source


def test_web_app_exposes_bridge_action_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/plan-bridge-action"' in source
    assert '"/api/run-bridge-action"' in source
    assert '"/api/enqueue-bridge-actions"' in source
    assert "plan_bridge_action" in source
    assert "run_bridge_action" in source
    assert "enqueue_bridge_actions" in source


def test_web_app_exposes_completeness_audit_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/completeness-audit"' in source
    assert "audit_research_completeness" in source


def test_web_app_exposes_cockpit_readiness_api() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/cockpit-readiness"' in source
    assert "audit_cockpit_readiness" in source


def test_web_app_exposes_graph_candidate_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/graph-candidates"' in source
    assert '"/api/generate-graph-candidates"' in source
    assert '"/api/review-graph-candidate"' in source
    assert '"/api/export-reviewed-graph"' in source
    assert "generate_graph_candidates" in source
    assert "list_graph_candidates" in source
    assert "review_graph_candidate" in source
    assert "export_reviewed_graph" in source


def test_web_app_exposes_source_inbox_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/source-inbox"' in source
    assert '"/api/source-inbox/add"' in source
    assert '"/api/source-inbox/import"' in source
    assert '"/api/source-inbox/reject"' in source
    assert "get_source_inbox" in source


def test_web_app_exposes_explicit_gate_and_review_queue_apis() -> None:
    web_app = Path(__file__).resolve().parents[1] / "src" / "question_research_poc" / "web_app.py"
    source = web_app.read_text(encoding="utf-8")

    assert '"/api/gate-details"' in source
    assert '"/api/review-queue"' in source
    assert "get_gate_details" in source
    assert "get_review_queue" in source


def test_cli_config_status_uses_runtime_config(capsys) -> None:
    assert cli_main(["config-status"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["ok"] is True
    assert payload["runtime_config"] == str(RUNTIME_CONFIG_PATH)
    assert payload["web"]["host"] == web_host()
    assert payload["web"]["port"] == web_port()
    assert payload["web"]["url"] == web_url()
    assert payload["project"]["default_root"] == str(default_project_root())


def test_counter_context_warning_is_nonblocking_for_guarded_final(tmp_path: Path) -> None:
    project = tmp_path / "counter-warning"
    init_project(project, "counter/context 缺口是否只是 warning？")
    source = add_source(project, title="高质量合成来源", path="local://fixture", source_type="local_fixture", quality="good")
    claim = add_claim(project, text="最终答案需要已审核支持证据。")
    support = add_evidence(project, claim_id=claim.id, source_id=source.id, quote_or_note="已审核支持证据", relation="supports")

    review_source(project, source_id=source.id, quality="good", reason="fixture source", reviewer="unit-test")
    review_evidence(project, evidence_id=support.id, status="verified", relation="supports", confidence="high", notes="accepted", reviewer="unit-test")

    audit = audit_research_completeness(project)

    assert audit["ready_for_answer"] is True
    assert audit["blocking_gates"] == []
    assert "missing_counter_evidence" in audit["warnings"]
    assert "missing_counter_evidence" not in audit["blocking_gates"]
    assert audit["coverage"]["claims_with_verified_support_evidence"] == 1
    assert audit["coverage"]["required_review_queue_count"] == 0
    assert audit["human_review_required"] is False
    assert any(item["item_type"] == "missing_counter_evidence" and item["severity"] == "warning" for item in audit["items"])

    queue = build_review_queue(project)
    counter_items = [item for item in queue if item["item_type"] == "missing_counter_evidence"]
    assert counter_items[0]["status"] == "recommended_review"
    assert counter_items[0]["requires_human_confirmation"] is False

    final = export_final_answer(project)
    assert final["ok"] is True
    markdown = Path(final["files"]["markdown"]).read_text(encoding="utf-8")
    assert "Status: ready_for_answer" in markdown
    assert "missing_counter_evidence" in markdown


def test_verified_support_evidence_and_quality_gates_remain_hard(tmp_path: Path) -> None:
    project = tmp_path / "negative-gates"
    init_project(project, "哪些 gate 仍然必须阻塞？")
    good = add_source(project, title="好来源", path="local://good", source_type="local_fixture", quality="good")
    claim = add_claim(project, text="只有 context 不足以导出最终答案。")
    context = add_evidence(project, claim_id=claim.id, source_id=good.id, quote_or_note="只有上下文", relation="context")
    review_source(project, source_id=good.id, quality="good", reason="fixture", reviewer="unit-test")
    review_evidence(project, evidence_id=context.id, status="verified", relation="context", confidence="medium", reviewer="unit-test")

    audit = audit_research_completeness(project)

    assert audit["ready_for_answer"] is False
    assert "claim_without_verified_evidence" in audit["blocking_gates"]
    assert "missing_counter_evidence" not in audit["warnings"]
    assert export_final_answer(project)["ok"] is False

    recovered = tmp_path / "rejected-poor-source-recovers"
    init_project(recovered, "拒绝低质量证据后是否能恢复？")
    good = add_source(recovered, title="好来源", path="local://good", source_type="local_fixture", quality="good")
    poor = add_source(recovered, title="低质量来源", path="local://poor", source_type="local_fixture", quality="poor")
    claim = add_claim(recovered, text="最终答案只纳入好来源支持证据。")
    support = add_evidence(recovered, claim_id=claim.id, source_id=good.id, quote_or_note="好来源支持", relation="supports")
    poor_candidate = add_evidence(recovered, claim_id=claim.id, source_id=poor.id, quote_or_note="低质量候选", relation="supports")
    review_source(recovered, source_id=good.id, quality="good", reason="fixture", reviewer="unit-test")
    review_evidence(recovered, evidence_id=support.id, status="verified", relation="supports", confidence="high", reviewer="unit-test")
    review_evidence(recovered, evidence_id=poor_candidate.id, status="rejected", relation="supports", confidence="low", reviewer="unit-test")

    recovered_audit = audit_research_completeness(recovered)

    assert recovered_audit["ready_for_answer"] is True
    assert "poor_source_evidence" not in recovered_audit["blocking_gates"]
    assert recovered_audit["coverage"]["poor_source_evidence"] == 0


def test_guarded_e2e_fixture_is_recoverable_and_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "fixture"

    partial = run_guarded_e2e_fixture(project, reviewer="fixture-reviewer", stop_after="evidence")
    assert partial["status"] == "stopped_after_evidence"
    assert partial["last_completed_stage"] == "evidence"
    assert len(list_records(project, "evidence")) == 2

    resumed = run_guarded_e2e_fixture(project, reviewer="fixture-reviewer")
    assert resumed["ok"] is True
    assert resumed["status"] == "complete"
    assert resumed["blocked_export_observed"] is True
    assert resumed["audit"]["ready_for_answer"] is True
    assert resumed["audit"]["blocking_gates"] == []
    assert "missing_counter_evidence" in resumed["audit"]["warnings"]
    assert resumed["final_export"]["ok"] is True
    assert resumed["external_services"]["ai_research_workflow_9082"] == "stopped_by_design"
    assert resumed["external_services"]["http_started"] is False
    assert resumed["external_services"]["external_api_called"] is False

    evidence_statuses = {row["quote_or_note"]: row["status"] for row in list_records(project, "evidence")}
    assert evidence_statuses["Synthetic support: reviewed support evidence unlocks final readiness."] == "verified"
    assert evidence_statuses["Synthetic rejected: this overbroad candidate must not enter the final answer."] == "rejected"
    assert {row.get("reviewer") for row in list_records(project, "reviews")} == {"fixture-reviewer"}

    counts = {kind: len(list_records(project, kind)) for kind in ("sources", "claims", "evidence", "reviews")}
    again = run_guarded_e2e_fixture(project, reviewer="fixture-reviewer")
    assert again["ok"] is True
    assert {kind: len(list_records(project, kind)) for kind in counts} == counts


def test_guarded_e2e_fixture_cli_and_mcp_entrypoints(tmp_path: Path, capsys) -> None:
    cli_project = tmp_path / "cli-fixture"
    assert cli_main(["run-guarded-e2e-fixture", "--project", str(cli_project), "--reviewer", "cli-reviewer"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "question_research_guarded_e2e_fixture.v1"
    assert payload["ok"] is True
    assert {row.get("reviewer") for row in list_records(cli_project, "reviews")} == {"cli-reviewer"}

    tools = {tool["name"] for tool in list_mcp_tools()}
    assert "run_guarded_e2e_fixture" in tools
    mcp_project = tmp_path / "mcp-fixture"
    mcp_payload = call_mcp_tool("run_guarded_e2e_fixture", {"root": str(mcp_project), "reviewer": "mcp-reviewer"})
    assert mcp_payload["ok"] is True
    assert mcp_payload["external_services"]["ai_research_workflow_9082"] == "stopped_by_design"
    assert {row.get("reviewer") for row in list_records(mcp_project, "reviews")} == {"mcp-reviewer"}

def test_guarded_e2e_fixture_state_schema_migrates_legacy_and_dedupes_receipts(tmp_path: Path) -> None:
    jsonschema = __import__("jsonschema")
    project = tmp_path / "legacy-state"
    project.mkdir(parents=True)
    legacy = {
        "schema": "question_research_guarded_e2e_fixture.v0",
        "stage": "evidence",
        "blocked_export_observed": True,
        "receipts": [
            {"id": "dup:receipt", "kind": "evidence", "record_id": "old", "status": "created"},
            {"id": "dup:receipt", "kind": "evidence", "record_id": "old", "status": "created"},
        ],
    }
    (project / FIXTURE_STATE_FILE).write_text(json.dumps(legacy), encoding="utf-8")

    payload = run_guarded_e2e_fixture(project, reviewer="migration-reviewer")
    state = json.loads((project / FIXTURE_STATE_FILE).read_text(encoding="utf-8"))

    assert payload["ok"] is True
    assert payload["schema_version"] == FIXTURE_STATE_SCHEMA_VERSION
    assert any("schema:" in item for item in payload["migrations"])
    assert len(state["receipts"]) == len({receipt["id"] for receipt in state["receipts"]})
    jsonschema.validate(state, FIXTURE_STATE_JSON_SCHEMA)


def test_guarded_e2e_fixture_recovers_from_truncated_state(tmp_path: Path) -> None:
    project = tmp_path / "truncated-state"
    partial = run_guarded_e2e_fixture(project, reviewer="recover-reviewer", stop_after="evidence")
    assert partial["status"] == "stopped_after_evidence"
    (project / FIXTURE_STATE_FILE).write_text("{", encoding="utf-8")

    recovered = run_guarded_e2e_fixture(project, reviewer="recover-reviewer")

    assert recovered["ok"] is True
    assert recovered["recovered_from_corrupt_state"] is True
    assert "corrupt_state_reinitialized" in recovered["migrations"]
    assert len(list_records(project, "sources")) == 1
    assert len(list_records(project, "claims")) == 1
    assert len(list_records(project, "evidence")) == 2


def test_guarded_e2e_fixture_detects_evidence_hash_drift(tmp_path: Path) -> None:
    project = tmp_path / "hash-drift"
    partial = run_guarded_e2e_fixture(project, reviewer="hash-reviewer", stop_after="evidence")
    assert partial["status"] == "stopped_after_evidence"
    state = json.loads((project / FIXTURE_STATE_FILE).read_text(encoding="utf-8"))
    support_id = state["stages"]["evidence"]["ids"]["support_evidence_id"]
    evidence_path = project_paths(project)["evidence"]
    rows = list_records(project, "evidence")
    for row in rows:
        if row["id"] == support_id:
            row["quote_or_note"] = "tampered synthetic support evidence"
    rewrite_jsonl(evidence_path, rows)

    drifted = run_guarded_e2e_fixture(project, reviewer="hash-reviewer")

    assert drifted["ok"] is False
    assert drifted["status"] == "evidence_hash_drift_detected"
    assert drifted["hash_drift_detected"][0]["evidence_key"] == "support"
    assert drifted["final_export"] == {}
    assert not (project / "exports" / "final-answer" / "final-answer.md").exists()


def test_guarded_e2e_fixture_blocks_unauthorized_final_export(tmp_path: Path) -> None:
    project = tmp_path / "unauthorized-export"
    partial = run_guarded_e2e_fixture(project, reviewer="export-reviewer", stop_after="evidence")
    assert partial["status"] == "stopped_after_evidence"

    blocked = export_final_answer(project)
    assert blocked["ok"] is False
    assert blocked["blocked"] is True
    assert "candidate_evidence_not_reviewed" in blocked["blocking_gates"]

    incomplete = export_final_answer(project, allow_incomplete=True)
    assert incomplete["ok"] is True
    assert incomplete["ready_for_answer"] is False
    assert incomplete["allow_incomplete"] is True
    incomplete_text = Path(incomplete["files"]["markdown"]).read_text(encoding="utf-8")
    assert "Status: incomplete_export" in incomplete_text
    assert "Status: ready_for_answer" not in incomplete_text

    finished = run_guarded_e2e_fixture(project, reviewer="export-reviewer")
    assert finished["ok"] is True
    assert finished["final_export"]["ready_for_answer"] is True


def test_guarded_e2e_fixture_seeded_random_replay_sequences(tmp_path: Path) -> None:
    seeds = [20260728, 17, 91]
    actions = ["full", "intake", "evidence", "blocked", "review", "truncate_state", "legacy_state", "duplicate_receipt"]
    for seed in seeds:
        rng = random.Random(seed)
        project = tmp_path / f"random-{seed}"
        for _ in range(24):
            action = rng.choice(actions)
            if action in {"intake", "evidence", "blocked", "review"}:
                run_guarded_e2e_fixture(project, reviewer=f"seed-{seed}", stop_after=action)
            elif action == "truncate_state" and (project / FIXTURE_STATE_FILE).exists():
                (project / FIXTURE_STATE_FILE).write_text("{", encoding="utf-8")
            elif action == "legacy_state":
                project.mkdir(parents=True, exist_ok=True)
                (project / FIXTURE_STATE_FILE).write_text(json.dumps({"schema": "legacy", "stage": "blocked", "receipts": []}), encoding="utf-8")
            elif action == "duplicate_receipt":
                project.mkdir(parents=True, exist_ok=True)
                state_path = project / FIXTURE_STATE_FILE
                if state_path.exists():
                    try:
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        state = {"schema": "legacy", "receipts": []}
                else:
                    state = {"schema": "legacy", "receipts": []}
                state.setdefault("receipts", []).extend([
                    {"id": "random:duplicate", "kind": "test", "record_id": "x", "status": "seen"},
                    {"id": "random:duplicate", "kind": "test", "record_id": "x", "status": "seen"},
                ])
                state_path.write_text(json.dumps(state), encoding="utf-8")
            else:
                run_guarded_e2e_fixture(project, reviewer=f"seed-{seed}")

        final = run_guarded_e2e_fixture(project, reviewer=f"seed-{seed}")
        state = json.loads((project / FIXTURE_STATE_FILE).read_text(encoding="utf-8"))

        assert final["ok"] is True
        assert final["external_services"]["ai_research_workflow_9082"] == "stopped_by_design"
        assert final["external_services"]["http_started"] is False
        assert final["external_services"]["external_api_called"] is False
        assert len(list_records(project, "sources")) == 1
        assert len(list_records(project, "claims")) == 1
        assert len(list_records(project, "evidence")) == 2
        assert {row["status"] for row in list_records(project, "evidence")} == {"verified", "rejected"}
        assert len(state["receipts"]) == len({receipt["id"] for receipt in state["receipts"]})
        assert not final["hash_drift_detected"]
