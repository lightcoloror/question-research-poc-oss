from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    return _configured_path("QRP_WORKSPACE_ROOT", PROJECT_ROOT.parent)


def tool_registry_path() -> Path:
    return _configured_path("LOCAL_TOOL_REGISTRY_PATH", workspace_root() / "tool-registry.json")


def ai_research_root() -> Path:
    return _configured_path("AI_RESEARCH_WORKFLOW_ROOT", workspace_root() / "ai-research-workflow")


def web_content_fetcher_root() -> Path:
    return _configured_path("WEB_CONTENT_FETCHER_ROOT", workspace_root() / "web-content-fetcher")


def video_knowledge_root() -> Path:
    return _configured_path("VIDEO_KNOWLEDGE_PIPELINE_ROOT", workspace_root() / "video-knowledge-pipeline")


def _configured_path(environment_name: str, fallback: Path) -> Path:
    value = os.environ.get(environment_name)
    return Path(value).expanduser().resolve() if value else fallback.resolve()
