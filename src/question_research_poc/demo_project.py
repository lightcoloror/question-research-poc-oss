from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .graph_candidates import generate_graph_candidates, list_graph_candidates
from .models import project_paths
from .orchestrator import add_claim, add_evidence, add_source, init_project, review_evidence, review_source
from .review_state import build_review_queue
from .source_inbox import add_inbox_item
from .storage import write_json
from .tool_bridge_status import build_tool_bridge_status
from .workflow_engine import audit_research_gates, route_research_task


DEMO_SCHEMA = "question_research_demo_project.v1"


def build_demo_project(root: str | Path) -> dict[str, Any]:
    """Build a deterministic, local-only demo project for cockpit smoke tests."""
    project_root = Path(root)
    _reset_known_project_files(project_root)

    project = init_project(project_root, "如何判断一个知识类视频是否值得系统学习？")
    good = add_source(project_root, title="高质量课程讲义", url="https://example.com/good-lecture-notes", quality="unknown", notes="Demo source; should be reviewed as good.")
    unknown = add_source(project_root, title="待判断搜索结果", url="https://example.com/unknown-search-result", quality="unknown")
    poor = add_source(project_root, title="低质量转载页", url="https://example.com/low-quality-repost", quality="poor", notes="Demo poor source.")
    video = add_source(project_root, title="知识视频处理包", path="D:/demo/video-run/webui-bundle", source_type="video_bundle", quality="unknown", notes="Imported from video-knowledge-pipeline as candidate material.")

    review_source(project_root, source_id=good.id, quality="good", reason="Demo: 作者、结构和证据链清晰。", reviewer="demo")

    core = add_claim(project_root, text="知识视频需要同时检查讲述内容、画面信息和来源质量。")
    candidate = add_claim(project_root, text="视频处理包导入的结论必须先作为候选证据。")
    unsupported = add_claim(project_root, text="无证据主张应该在驾驶舱中显式暴露。")

    verified_evidence = add_evidence(
        project_root,
        claim_id=core.id,
        source_id=good.id,
        quote_or_note="讲义明确要求同时核对音频转写、屏幕文字和图表。",
        relation="supports",
        confidence="medium",
    )
    review_evidence(project_root, evidence_id=verified_evidence.id, status="verified", relation="supports", confidence="high", notes="Demo verified evidence.")
    add_evidence(
        project_root,
        claim_id=core.id,
        source_id=unknown.id,
        quote_or_note="搜索结果声称该流程适合所有知识视频，但尚未核验来源。",
        relation="context",
        confidence="low",
    )
    add_evidence(
        project_root,
        claim_id=candidate.id,
        source_id=video.id,
        quote_or_note="视频 bundle 中提取出一个待审核知识点。",
        relation="supports",
        confidence="unknown",
    )
    add_evidence(
        project_root,
        claim_id=candidate.id,
        source_id=poor.id,
        quote_or_note="转载页给出类似结论，但来源质量低，只能作为线索。",
        relation="supports",
        confidence="low",
    )

    add_inbox_item(
        project_root,
        kind="video_bundle",
        title="待导入视频 run",
        location="D:/demo/pending-video/webui-bundle",
        source_tool="video-knowledge-pipeline",
        quality_hint="unknown",
    )
    add_inbox_item(
        project_root,
        kind="web_page",
        title="待判断网页",
        url="https://example.com/pending-page",
        source_tool="web-content-fetcher",
        quality_hint="unknown",
    )

    route_research_task(project_root, write=True)
    gate_audit = audit_research_gates(project_root, target_stage="answer_draft", write=True)
    graph = generate_graph_candidates(project_root)
    _write_demo_tool_run(project_root)
    _write_demo_fetched_source(project_root)

    review_queue = build_review_queue(project_root)
    bridge = build_tool_bridge_status(project_root)
    return {
        "ok": True,
        "schema": DEMO_SCHEMA,
        "root": str(project_root),
        "project_id": project.id,
        "question": project.question,
        "counts": {
            "sources": 4,
            "claims": 3,
            "review_queue": len(review_queue),
            "graph_candidates": list_graph_candidates(project_root)["counts"]["total"],
            "tool_runs": len(bridge["recent_runs"]),
        },
        "gate_audit": {"ok": gate_audit.get("ok"), "next_gate": gate_audit.get("next_gate"), "blockers": gate_audit.get("blockers", [])},
        "review_queue": review_queue,
        "graph": {"schema": graph["schema"], "added_count": graph["added_count"], "counts": graph["counts"]},
        "tool_bridge_status": {"schema": bridge["schema"], "recent_runs": bridge["recent_runs"][:3]},
    }


def _reset_known_project_files(root: Path) -> None:
    paths = project_paths(root)
    root.mkdir(parents=True, exist_ok=True)
    known_names = {
        paths["project"].name,
        paths["sources"].name,
        paths["source_reviews"].name,
        paths["claims"].name,
        paths["evidence"].name,
        paths["graph"].name,
        paths["reviews"].name,
        "task-route.json",
        "gate-audit.json",
        "workflow-next-steps.json",
        "research-plan.json",
        "source-inbox.jsonl",
        "work-queue.jsonl",
        "notes",
        "state",
        "tool-runs",
        "fetched-sources",
        "exports",
    }
    for child in root.iterdir():
        if child.name not in known_names:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _write_demo_tool_run(root: Path) -> None:
    run_dir = root / "state" / "tool-runs" / "demo-web-fetch"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "result.json",
        {
            "tool_id": "web-content-fetcher",
            "action": "health",
            "dry_run": True,
            "executed": False,
            "response": {"ok": True},
            "result_path": str(root / "fetched-sources" / "demo-source.json"),
            "markdown_path": str(root / "fetched-sources" / "demo-source.md"),
        },
    )


def _write_demo_fetched_source(root: Path) -> None:
    fetched = root / "fetched-sources"
    fetched.mkdir(parents=True, exist_ok=True)
    (fetched / "demo-source.md").write_text("# Demo fetched source\n\nThis is a deterministic local fixture artifact.\n", encoding="utf-8")
    write_json(fetched / "demo-source.json", {"ok": True, "title": "Demo fetched source", "url": "https://example.com/demo"})
