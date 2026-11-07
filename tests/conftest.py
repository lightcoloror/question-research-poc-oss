from __future__ import annotations

import json
from pathlib import Path

import pytest
import socket


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Public synthetic tests never contact services or a local proxy."""
    def blocked(*args, **kwargs):
        raise OSError("Network is outside the offline public test scope")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


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
