from __future__ import annotations

import json
import hashlib
from pathlib import Path

from question_research_poc.research_output import research_output_schema_path
from question_research_poc.runtime_config import PROJECT_ROOT, default_project_root
from question_research_poc.runtime_paths import (
    ai_research_root,
    tool_registry_path,
    video_knowledge_root,
    web_content_fetcher_root,
    workspace_root,
)
from question_research_poc.local_tool_health import build_local_tool_health_dashboard
from question_research_poc.tool_executor import run_local_tool_action
from question_research_poc.web_app import _tools_payload


def test_runtime_paths_use_environment_overrides(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    registry = tmp_path / "registry.json"
    ai_root = tmp_path / "ai"
    web_root = tmp_path / "web"
    video_root = tmp_path / "video"
    monkeypatch.setenv("QRP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_TOOL_REGISTRY_PATH", str(registry))
    monkeypatch.setenv("AI_RESEARCH_WORKFLOW_ROOT", str(ai_root))
    monkeypatch.setenv("WEB_CONTENT_FETCHER_ROOT", str(web_root))
    monkeypatch.setenv("VIDEO_KNOWLEDGE_PIPELINE_ROOT", str(video_root))

    assert workspace_root() == workspace.resolve()
    assert tool_registry_path() == registry.resolve()
    assert ai_research_root() == ai_root.resolve()
    assert web_content_fetcher_root() == web_root.resolve()
    assert video_knowledge_root() == video_root.resolve()


def test_registry_callers_resolve_environment_override_at_call_time(
    synthetic_tool_registry: Path,
) -> None:
    health = build_local_tool_health_dashboard()
    action = run_local_tool_action("video-knowledge-pipeline", "health")
    web = _tools_payload()

    assert Path(health["registry"]) == synthetic_tool_registry.resolve()
    assert action["dry_run"] is True
    assert "asr-env-status" in action["command"]
    assert Path(web["registry"]) == synthetic_tool_registry.resolve()


def test_relative_default_project_root_resolves_from_repository() -> None:
    config = {"project": {"default_root": ".research-question"}}
    assert default_project_root(config) == PROJECT_ROOT / ".research-question"


def test_packaged_schema_mirror_matches_canonical_schema() -> None:
    canonical = PROJECT_ROOT / "schemas" / "research-output.v1.schema.json"
    packaged = PROJECT_ROOT / "src" / "question_research_poc" / "schemas" / "research-output.v1.schema.json"

    assert json.loads(canonical.read_text(encoding="utf-8")) == json.loads(packaged.read_text(encoding="utf-8"))
    assert canonical.read_bytes() == packaged.read_bytes()
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == "3c2e0e9a05034b1ffa3693735da128c7d3e114ddb155f11668120b974fee1009"
    assert research_output_schema_path() == canonical
