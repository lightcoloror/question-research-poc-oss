from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import now_iso
from .runtime_paths import tool_registry_path


IMPORTANT_TOOLS = [
    "ai-research-workflow",
    "web-content-fetcher",
    "video-knowledge-pipeline",
    "video-download-orchestrator",
]


def build_local_tool_health_dashboard(registry_path: str | Path | None = None) -> dict[str, Any]:
    registry_file = Path(registry_path) if registry_path is not None else tool_registry_path()
    registry = _read_registry(registry_file)
    tools = registry.get("tools", {}) if isinstance(registry, dict) else {}
    rows = [_tool_row(name, tools.get(name)) for name in IMPORTANT_TOOLS]
    available_count = sum(1 for row in rows if row["available"])
    return {
        "ok": True,
        "schema": "question_research_local_tool_health.v1",
        "registry": str(registry_file),
        "registry_exists": registry_file.exists(),
        "last_checked": now_iso(),
        "mode": "metadata_only",
        "summary": {
            "total": len(rows),
            "available": available_count,
            "missing": len(rows) - available_count,
            "needs_attention": sum(1 for row in rows if row["needs_attention"]),
        },
        "tools": rows,
        "recommended_next_action": _overall_next_action(rows),
    }


def _tool_row(name: str, info: Any) -> dict[str, Any]:
    if not isinstance(info, dict):
        return {
            "name": name,
            "available": False,
            "needs_attention": True,
            "status": "missing_registry_entry",
            "interface": "",
            "path": "",
            "path_exists": False,
            "discovery": "",
            "discovery_exists": False,
            "health_command": "",
            "recommended_next_action": "检查 LOCAL_TOOL_REGISTRY_PATH 指向的 registry 是否包含该工具。",
        }
    tool_path = Path(str(info.get("path") or ""))
    discovery = Path(str(info.get("discovery_markdown") or ""))
    preferred = info.get("preferred_interfaces") if isinstance(info.get("preferred_interfaces"), list) else []
    health = info.get("health_check") if isinstance(info.get("health_check"), dict) else {}
    path_exists = bool(str(tool_path) and tool_path.exists())
    discovery_exists = bool(str(discovery) and discovery.exists())
    available = path_exists and discovery_exists
    return {
        "name": name,
        "available": available,
        "needs_attention": not available,
        "status": "available" if available else "missing_local_path_or_discovery",
        "interface": str(preferred[0]) if preferred else "",
        "preferred_interfaces": preferred,
        "path": str(tool_path),
        "path_exists": path_exists,
        "discovery": str(discovery),
        "discovery_exists": discovery_exists,
        "health_command": str(health.get("command") or ""),
        "recommended_next_action": _tool_next_action(name, available, preferred),
        "purpose": str(info.get("purpose") or ""),
    }


def _tool_next_action(name: str, available: bool, preferred: list[Any]) -> str:
    if not available:
        return f"先通过 local-tools discover {name} 或检查 registry/discovery 路径。"
    interface = str(preferred[0]) if preferred else "cli"
    if name == "ai-research-workflow":
        return "用搜索计划或搜索并导入入口推进来源收集。"
    if name == "web-content-fetcher":
        return "在来源面板选择 source 后生成抓取计划或候选 evidence。"
    if name == "video-knowledge-pipeline":
        return "用视频处理计划生成 review bundle，再导入视频知识包。"
    if name == "video-download-orchestrator":
        return "下载需求先到该工具生成下载计划，确认后再执行。"
    return f"优先使用 {interface} 接口。"


def _overall_next_action(rows: list[dict[str, Any]]) -> str:
    missing = [row["name"] for row in rows if not row["available"]]
    if missing:
        return "先修复这些本地工具注册或 discovery 路径：" + ", ".join(missing)
    return "关键本地工具元数据齐全；按当前研究卡点选择搜索、抓取、视频处理或下载计划。"


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"tools": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"tools": {}}
