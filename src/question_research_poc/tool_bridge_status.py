from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from .ai_research_bridge import ai_research_status
from .bridge_runs import list_bridge_runs
from .local_tool_health import build_local_tool_health_dashboard
from .review_state import build_review_queue
from .source_inbox import get_source_inbox


BRIDGE_TOOLS = [
    "ai-research-workflow",
    "web-content-fetcher",
    "video-knowledge-pipeline",
]


def build_tool_bridge_status(root: str | Path, *, limit: int = 8) -> dict[str, Any]:
    """Read the controller-side state for external tool bridges.

    This is intentionally read-only. The bridge workbench should show what
    happened, what was imported, what still needs review, and where artifacts
    are stored without reimplementing search/fetch/video logic here.
    """
    project_root = Path(root)
    bridge_runs = list_bridge_runs(project_root, limit=limit)
    recent_runs = bridge_runs.get("runs", [])
    inbox = get_source_inbox(project_root)
    review_queue = build_review_queue(project_root)
    fetched_sources = _fetched_sources(project_root, limit=limit)
    health = build_local_tool_health_dashboard()
    live = _live_bridge_checks()
    tools = _tool_rows(health, recent_runs, live)
    backend_mode = _backend_mode(live, tools)
    return {
        "ok": True,
        "schema": "question_research_tool_bridge_status.v1",
        "root": str(project_root),
        "mode": "read_only_controller_state",
        "backend_mode": backend_mode,
        "backend_mode_label": _backend_mode_label(backend_mode),
        "backend_summary": _backend_summary(backend_mode, live),
        "tools": tools,
        "live_checks": live,
        "fallback_scope": _fallback_scope(backend_mode),
        "recent_runs": recent_runs,
        "bridge_runs": bridge_runs,
        "fetched_sources": fetched_sources,
        "source_inbox": {
            "path": inbox.get("path", ""),
            "counts": inbox.get("counts", {}),
            "pending_items": [item for item in inbox.get("items", []) if item.get("import_status") == "candidate"],
        },
        "review_queue": {
            "count": len(review_queue),
            "by_type": _counts_by_key(review_queue, "item_type"),
            "items": review_queue[:limit],
        },
        "operator_boundary": [
            "This status view does not run search, fetch, video processing, or imports.",
            "External tools remain delegated modules; this project stores plans, artifacts, candidates, and review gates.",
            "Imported sources and evidence remain subject to human review.",
        ],
        "next_actions": _next_actions(recent_runs, inbox.get("counts", {}), review_queue, live),
    }


def _tool_rows(health: dict[str, Any], recent_runs: list[dict[str, Any]], live: dict[str, Any]) -> list[dict[str, Any]]:
    health_by_name = {str(item.get("name", "")): item for item in health.get("tools", []) if isinstance(item, dict)}
    rows = []
    for tool in BRIDGE_TOOLS:
        runs = [run for run in recent_runs if str(run.get("tool", "")) == tool]
        last = runs[0] if runs else {}
        health_row = health_by_name.get(tool, {})
        live_row = live.get(tool, {}) if isinstance(live.get(tool), dict) else {}
        metadata_available = bool(health_row.get("available", False))
        live_ok = bool(live_row.get("ok", True))
        available = metadata_available and live_ok
        recovery = str(live_row.get("recovery_hint") or live_row.get("next_action") or "")
        rows.append(
            {
                "name": tool,
                "available": available,
                "metadata_available": metadata_available,
                "live_ok": live_ok,
                "status": "available" if available else ("service_unreachable" if metadata_available and not live_ok else "missing_local_path_or_discovery"),
                "interface": health_row.get("interface", ""),
                "recommended_next_action": recovery or health_row.get("recommended_next_action", ""),
                "live_check": live_row,
                "recent_run_count": len(runs),
                "last_run": last,
                "last_error": last.get("error", ""),
                "last_artifact": last.get("path", ""),
            }
        )
    return rows


def _live_bridge_checks() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        status = ai_research_status(timeout_seconds=1)
        checks["ai-research-workflow"] = {
            "ok": bool(status.get("ok")),
            "base_url": status.get("base_url", ""),
            "error": status.get("error", ""),
            "next_action": status.get("next_action", ""),
            "recovery_hint": status.get("next_action", ""),
            "mode": "live_http_health",
        }
    except Exception as exc:
        checks["ai-research-workflow"] = {
            "ok": False,
            "base_url": "",
            "error": str(exc),
            "next_action": "ai-research-workflow live health check failed; pause 9082/8928 dependent search and use cached/local-only fallback.",
            "recovery_hint": "ai-research-workflow live health check failed; pause 9082/8928 dependent search and use cached/local-only fallback.",
            "mode": "live_http_health",
        }
    checks["searxng-native"] = _tcp_service_check(
        "searxng-native",
        "127.0.0.1",
        8928,
        "SearXNG native dependency is not listening; pause search flows that depend on live web discovery, but keep local review/export and explicit URL fetch available.",
    )
    return checks


def _tcp_service_check(name: str, host: str, port: int, recovery_hint: str) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=1):
            return {"ok": True, "tool": name, "host": host, "port": port, "base_url": f"http://{host}:{port}", "error": "", "recovery_hint": "", "mode": "tcp_listener"}
    except OSError as exc:
        return {"ok": False, "tool": name, "host": host, "port": port, "base_url": f"http://{host}:{port}", "error": str(exc), "recovery_hint": recovery_hint, "mode": "tcp_listener"}


def _backend_mode(live: dict[str, Any], tools: list[dict[str, Any]]) -> str:
    ai = live.get("ai-research-workflow") if isinstance(live.get("ai-research-workflow"), dict) else {}
    searxng = live.get("searxng-native") if isinstance(live.get("searxng-native"), dict) else {}
    if ai.get("ok") and searxng.get("ok"):
        return "full_research"
    if ai.get("ok") and not searxng.get("ok"):
        return "degraded_local_only"
    available_local = any(tool.get("metadata_available") for tool in tools if tool.get("name") in {"web-content-fetcher", "video-knowledge-pipeline"})
    return "degraded_local_only" if available_local else "blocked"


def _backend_mode_label(mode: str) -> str:
    return {
        "full_research": "完整研究模式",
        "degraded_local_only": "本地候选 / 降级模式",
        "blocked": "阻塞模式",
    }.get(mode, "未知模式")


def _backend_summary(mode: str, live: dict[str, Any]) -> str:
    if mode == "full_research":
        return "ai-research-workflow 与 SearXNG 依赖均可用，可以执行 deep-research/search live 动作。"
    if mode == "degraded_local_only":
        ai = live.get("ai-research-workflow") if isinstance(live.get("ai-research-workflow"), dict) else {}
        if ai.get("ok"):
            return "ai-research-workflow 可用，但 SearXNG 依赖不可用或未确认；优先使用本地缓存、明确 URL 抓取和候选导入。"
        return "ai-research-workflow 当前不可用；暂停依赖 9082/8928 的搜索，保留本地缓存、明确 URL 抓取、视频 bundle 和人工导入。"
    return "关键后端与本地桥接都不可用；先恢复服务或只做人工审核/已有 artifact 阅读。"


def _fallback_scope(mode: str) -> list[str]:
    if mode == "full_research":
        return ["deep-research/search live actions", "explicit URL web fetch", "cached artifacts", "existing video bundles", "human-reviewed candidate imports"]
    return ["cached artifacts", "explicit URL WCF fetches", "bookwiki/local docs", "existing video bundles", "human-reviewed candidate imports"]


def _recent_tool_runs(root: Path, *, limit: int) -> list[dict[str, Any]]:
    paths = []
    for run_dir in (root / "state" / "tool-runs", root / "tool-runs"):
        if run_dir.exists():
            paths.extend(run_dir.glob("*.json"))
            paths.extend(run_dir.glob("*/result.json"))
    if not paths:
        return []
    rows = []
    for path in sorted(set(paths), key=lambda item: item.stat().st_mtime, reverse=True)[: max(limit, 1)]:
        rows.append(_summarize_run(path))
    return rows


def _summarize_run(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            data = parsed
    except Exception as exc:
        return {"path": str(path), "ok": False, "tool": "unknown", "error": str(exc)}
    return {
        "path": str(path),
        "ok": _run_ok(data),
        "tool": _run_tool(data),
        "kind": _run_kind(path, data),
        "query_or_url": _run_query_or_url(data),
        "counts": _run_counts(data),
        "result_paths": _run_result_paths(data),
        "error": _run_error(data),
    }


def _run_ok(data: dict[str, Any]) -> bool:
    if "error" in data:
        return False
    response = data.get("response")
    if isinstance(response, dict) and response.get("ok") is False:
        return False
    return True


def _run_tool(data: dict[str, Any]) -> str:
    tool_id = str(data.get("tool_id") or "")
    if tool_id:
        return tool_id
    source = str(data.get("source") or "")
    if source in {"ai-research-workflow", "web-content-fetcher", "video-knowledge-pipeline"}:
        return source
    plan = data.get("plan")
    if isinstance(plan, dict):
        tool = str(plan.get("tool") or "")
        if tool:
            return tool
    if "ai-research" in source:
        return "ai-research-workflow"
    return source or "unknown"


def _run_kind(path: Path, data: dict[str, Any]) -> str:
    if data.get("action"):
        return str(data.get("action"))
    if "request" in data and _run_tool(data) == "web-content-fetcher":
        return "fetch_source_content"
    if "counts" in data and "input" in data:
        return "import_ai_research_result"
    name = path.stem
    return name.rsplit("-", 6)[0] if "-" in name else name


def _run_query_or_url(data: dict[str, Any]) -> str:
    request = data.get("request") if isinstance(data.get("request"), dict) else {}
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    return str(request.get("url") or request.get("topic") or plan.get("query") or plan.get("url") or "")


def _run_counts(data: dict[str, Any]) -> dict[str, Any]:
    counts = data.get("counts")
    if isinstance(counts, dict):
        return counts
    candidate = data.get("candidate_evidence")
    if isinstance(candidate, list):
        return {"candidate_evidence": len(candidate)}
    imported = data.get("imported")
    if isinstance(imported, dict) and isinstance(imported.get("counts"), dict):
        return imported["counts"]
    return {}


def _run_result_paths(data: dict[str, Any]) -> list[str]:
    paths = []
    for key in ("result_path", "markdown_path", "json_path", "import_path", "manifest_path", "note_path"):
        value = data.get(key)
        if value:
            paths.append(str(value))
    imported = data.get("imported")
    if isinstance(imported, dict) and imported.get("import_path"):
        paths.append(str(imported["import_path"]))
    return paths


def _run_error(data: dict[str, Any]) -> str:
    if data.get("error"):
        return str(data["error"])
    response = data.get("response")
    if isinstance(response, dict) and response.get("error"):
        return str(response["error"])
    return ""


def _fetched_sources(root: Path, *, limit: int) -> list[dict[str, Any]]:
    fetched_dir = root / "fetched-sources"
    if not fetched_dir.exists():
        return []
    rows = []
    for path in sorted(fetched_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[: max(limit, 1)]:
        rows.append({"path": str(path), "json_path": str(path.with_suffix(".json")), "title": path.stem})
    return rows


def _counts_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _next_actions(recent_runs: list[dict[str, Any]], inbox_counts: dict[str, Any], review_queue: list[dict[str, Any]], live: dict[str, Any]) -> list[str]:
    actions = []
    ai_live = live.get("ai-research-workflow") if isinstance(live.get("ai-research-workflow"), dict) else {}
    searxng_live = live.get("searxng-native") if isinstance(live.get("searxng-native"), dict) else {}
    if ai_live and not ai_live.get("ok"):
        actions.append("ai-research-workflow HTTP 后端当前不可达；暂停依赖 9082/8928 的搜索、深化、核验和自动候选来源发现。")
        actions.append("进入 cached/local-only fallback：只使用本地已缓存 artifact、明确 URL 的 WCF 抓取、bookwiki/本地文档、视频知识链已有 bundle 和人工导入候选材料。")
    elif searxng_live and not searxng_live.get("ok"):
        actions.append("SearXNG native 依赖当前不可达；deep-research/search 可能降级，优先使用明确 URL 抓取、本地缓存和候选导入。")
    if not recent_runs:
        actions.append("先从搜索、网页抓取或视频处理工作台生成一个计划或导入候选材料。")
    if int(inbox_counts.get("candidate", 0) or 0) > 0:
        actions.append("处理 source inbox 中的 candidate 材料：导入为来源或拒绝。")
    if review_queue:
        actions.append("处理审核队列：来源质量、候选证据、无证据主张和反证检查。")
    failures = [run for run in recent_runs if not run.get("ok")]
    if failures:
        actions.append("查看最近失败的 tool-run JSON，先处理错误原因再重试。")
    return actions or ["外部工具桥接状态正常，可以继续推进 Gate 或导出审核包。"]
