from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def synthetic_tool_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tools: dict[str, dict[str, object]] = {}
    for name in (
        "question-research-poc",
        "ai-research-workflow",
        "web-content-fetcher",
        "video-knowledge-pipeline",
        "video-download-orchestrator",
    ):
        root = tmp_path / "local-tools" / name
        root.mkdir(parents=True)
        discovery = root / "AGENT_DISCOVERY.md"
        discovery.write_text(f"# Synthetic discovery for {name}\n", encoding="utf-8")
        health_command = "python -m synthetic_tool health"
        if name == "video-knowledge-pipeline":
            health_command = "python -m video_knowledge_pipeline.cli asr-env-status"
        tools[name] = {
            "path": str(root),
            "discovery_markdown": str(discovery),
            "preferred_interfaces": ["cli"],
            "health_check": {
                "command": health_command,
                "working_directory": str(root),
            },
        }

    registry = tmp_path / "tool-registry.synthetic.json"
    registry.write_text(json.dumps({"tools": tools}, indent=2), encoding="utf-8")
    monkeypatch.setenv("LOCAL_TOOL_REGISTRY_PATH", str(registry))
    return registry
