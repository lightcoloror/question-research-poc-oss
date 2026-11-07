from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .models import new_id, now_iso
from .runtime_paths import tool_registry_path
from .storage import write_json


TOOL_ACTION_SCHEMA = "question_research_tool_action.v1"


def run_local_tool_action(
    tool_id: str,
    action: str,
    *,
    args: dict[str, Any] | None = None,
    execute: bool = False,
    timeout_seconds: int = 60,
    project_root: str | Path | None = None,
    task_id: str = "",
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    registry = _read_registry(Path(registry_path) if registry_path is not None else tool_registry_path())
    tool = _tool_info(registry, tool_id)
    action_plan = _build_action_plan(tool_id, action, tool, args or {})
    result = {
        "ok": True,
        "schema": TOOL_ACTION_SCHEMA,
        "tool_id": tool_id,
        "action": action,
        "dry_run": not execute,
        "executed": False,
        "command": action_plan["command"],
        "cwd": action_plan.get("cwd", tool.get("path", "")),
        "artifact_paths": action_plan.get("artifact_paths", []),
        "expected_effect": action_plan.get("expected_effect", "metadata_only"),
        "requires_human_confirmation": bool(action_plan.get("requires_human_confirmation", False)),
        "boundary": action_plan.get("boundary", "Whitelisted local-tool action only; no arbitrary shell commands."),
        "last_checked": now_iso(),
    }
    if not execute:
        return result
    if result["requires_human_confirmation"]:
        result["ok"] = False
        result["error"] = "action requires human confirmation; rerun only after explicit approval"
        return result
    if not str(action_plan.get("command") or "").strip():
        result["ok"] = False
        result["error"] = "action has no executable command"
        return result
    run_dir = _start_run_dir(project_root, tool_id, action) if project_root else None
    if run_dir:
        result["run_dir"] = str(run_dir)
        result["task_id"] = task_id
        (run_dir / "command.txt").write_text(str(action_plan["command"]), encoding="utf-8")
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", str(action_plan["command"])],
        cwd=str(result["cwd"] or "."),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    result.update(
        {
            "executed": True,
            "returncode": completed.returncode,
            "ok": completed.returncode == 0,
            "suggested_recovery": "" if completed.returncode == 0 else "查看 stdout/stderr artifact，修复工具环境或参数后重试。",
        }
    )
    if run_dir:
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        result_path = run_dir / "result.json"
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        result["stdout_path"] = str(stdout_path)
        result["stderr_path"] = str(stderr_path)
        result["result_path"] = str(result_path)
        result["artifact_paths"] = list(result.get("artifact_paths", [])) + [str(run_dir / "command.txt"), str(stdout_path), str(stderr_path), str(result_path)]
        write_json(result_path, result)
    else:
        result["stdout"] = completed.stdout
        result["stderr"] = completed.stderr
    return result


def allowed_tool_actions(tool_id: str | None = None) -> dict[str, list[str]]:
    actions = {
        "ai-research-workflow": ["health", "discover", "service_status"],
        "web-content-fetcher": ["health", "discover"],
        "video-knowledge-pipeline": ["health", "discover", "asr_status"],
        "video-download-orchestrator": ["health", "discover", "download_plan"],
    }
    return {tool_id: actions.get(tool_id, [])} if tool_id else actions


def _build_action_plan(tool_id: str, action: str, tool: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    allowed = allowed_tool_actions().get(tool_id, [])
    if action not in allowed:
        raise ValueError(f"action not allowed for {tool_id}: {action}")
    path = str(tool.get("path") or ".")
    discovery = str(tool.get("discovery_markdown") or "")
    health = tool.get("health_check") if isinstance(tool.get("health_check"), dict) else {}
    if action in {"health", "asr_status"}:
        return {
            "command": str(health.get("command") or ""),
            "cwd": str(health.get("working_directory") or path),
            "expected_effect": "metadata_only",
            "artifact_paths": [],
            "boundary": "Health/status check only. It should not fetch, download, process video, or write research decisions.",
        }
    if action == "discover":
        return {
            "command": f"Get-Content -LiteralPath '{discovery}'",
            "cwd": path,
            "expected_effect": "metadata_only",
            "artifact_paths": [discovery] if discovery else [],
            "boundary": "Reads the registered discovery document only.",
        }
    if tool_id == "ai-research-workflow" and action == "service_status":
        command = str(tool.get("cli", {}).get("service_status") or "python -m research_workflow.cli service status --format json")
        return {
            "command": command,
            "cwd": path,
            "expected_effect": "metadata_only",
            "artifact_paths": [],
            "boundary": "Service status only. Search execution remains a separate planned action.",
        }
    if tool_id == "video-download-orchestrator" and action == "download_plan":
        url = str(args.get("url") or "")
        if not url:
            raise ValueError("download_plan requires args.url")
        command = f"$env:PYTHONPATH='{path}\\src'; python -m video_orchestrator.cli download '{_ps_escape(url)}' --dry-run --format json"
        return {
            "command": command,
            "cwd": path,
            "expected_effect": "planning_only",
            "artifact_paths": [],
            "requires_human_confirmation": False,
            "boundary": "Dry-run download planning only. Real downloads require explicit external execution approval.",
        }
    raise ValueError(f"action plan not implemented for {tool_id}: {action}")


def _tool_info(registry: dict[str, Any], tool_id: str) -> dict[str, Any]:
    tools = registry.get("tools", {}) if isinstance(registry, dict) else {}
    tool = tools.get(tool_id)
    if not isinstance(tool, dict):
        raise ValueError(f"tool not found in registry: {tool_id}")
    return tool


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"tools": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"tools": {}}


def _ps_escape(value: str) -> str:
    return value.replace("'", "''")


def _start_run_dir(project_root: str | Path | None, tool_id: str, action: str) -> Path:
    root = Path(project_root or ".")
    safe_tool = _safe_slug(tool_id)
    safe_action = _safe_slug(action)
    run_dir = root / "state" / "tool-runs" / f"{now_iso().replace(':', '-')}-{safe_tool}-{safe_action}-{new_id('run').removeprefix('run_')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-") or "tool"
