from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge_runs import create_bridge_run
from .models import dataclass_to_dict, now_iso
from .orchestrator import add_claim, add_evidence, add_source, list_records
from .runtime_paths import ai_research_root, tool_registry_path
from .storage import ensure_project_dirs, load_project, write_json


AI_RESEARCH_ROOT = ai_research_root()
SERVICE_FILE = AI_RESEARCH_ROOT / ".research" / "service.json"
REGISTRY_PATH = tool_registry_path()
DEFAULT_AI_RESEARCH_URL = "http://127.0.0.1:9081"


def ai_research_status(base_url: str | None = None, *, timeout_seconds: int = 3) -> dict[str, Any]:
    discovery = discover_ai_research_service(base_url=base_url, timeout_seconds=timeout_seconds)
    health = discovery["checks"].get("/v1/health", {})
    metadata_available = bool(discovery.get("tool_root") or discovery.get("service_file") or discovery.get("registry_entry"))
    live_ok = bool(health.get("ok"))
    return {
        "ok": live_ok,
        "metadata_available": metadata_available,
        "live_ok": live_ok,
        "available": metadata_available and live_ok,
        "status": "available" if live_ok else "service_unreachable",
        "base_url": discovery["base_url"],
        "health": health.get("data") or {},
        "discovery": discovery,
        "error": health.get("error", ""),
        "next_action": discovery.get("recovery_hint", ""),
    }


def discover_ai_research_service(base_url: str | None = None, *, timeout_seconds: int = 10) -> dict[str, Any]:
    resolved = resolve_ai_research_url(base_url)
    service_config = _read_service_config()
    registry_entry = _read_registry_entry()
    checks: dict[str, Any] = {}
    for endpoint in ("/v1/health", "/v1/capabilities", "/v1/discovery"):
        try:
            data = _get_json(f"{resolved}{endpoint}", timeout=timeout_seconds)
            checks[endpoint] = {"ok": True, "data": data}
        except Exception as exc:
            checks[endpoint] = {"ok": False, "error": str(exc), "recovery_hint": _ai_research_recovery(str(exc))}
    ok = any(row.get("ok") for row in checks.values())
    return {
        "ok": ok,
        "schema": "question_research_ai_research_discovery.v1",
        "tool": "ai-research-workflow",
        "tool_root": str(registry_entry.get("path") or AI_RESEARCH_ROOT),
        "registry_path": str(REGISTRY_PATH),
        "registry_entry": registry_entry,
        "service_file": str(_service_file_from_registry(registry_entry) or SERVICE_FILE),
        "service_config": service_config,
        "base_url": resolved,
        "checks": checks,
        "capabilities": checks.get("/v1/capabilities", {}).get("data") or {},
        "discovery": checks.get("/v1/discovery", {}).get("data") or {},
        "recovery_hint": "" if ok else _ai_research_recovery("; ".join(str(row.get("error", "")) for row in checks.values())),
    }


def plan_ai_research_search(
    root: str | Path,
    *,
    query: str | None = None,
    mode: str = "auto",
    max_results: int = 8,
    deep: bool = False,
    no_network: bool = False,
    fetch: bool = True,
    import_results: bool = False,
    base_url: str | None = None,
) -> dict[str, Any]:
    project = load_project(root)
    resolved_query = query or project.question
    resolved_url = resolve_ai_research_url(base_url)
    endpoint = "/v1/deepen" if deep else "/v1/search"
    payload = {
        "topic": resolved_query,
        "mode": mode,
        "max_results": int(max_results),
        "no_network": bool(no_network),
        "fetch": bool(fetch),
    }
    result = {
        "ok": True,
        "tool": "ai-research-workflow",
        "base_url": resolved_url,
        "endpoint": endpoint,
        "method": "POST",
        "query": resolved_query,
        "payload": payload,
        "import_results": bool(import_results),
        "expected_outputs": ["sources", "claims", "evidence_candidates"],
        "delegation_boundary": "question-research-poc only plans, dispatches, imports candidates, and keeps human review gates; ai-research-workflow performs search/deepen/fetch.",
        "failure_next_action": "如果状态检查失败，先启动 ai-research-workflow HTTP 服务，或设置 AI_RESEARCH_WORKFLOW_URL/base_url 后重试。",
    }
    bridge_run = create_bridge_run(
        root,
        tool="ai-research-workflow",
        action="plan_ai_research_search",
        request={"query": resolved_query, **payload},
        endpoint=f"{resolved_url}{endpoint}",
        command=f"POST {resolved_url}{endpoint}",
        status="planned",
        response={"plan": {key: value for key, value in result.items() if key != "bridge_run"}},
    )
    result["bridge_run"] = bridge_run
    return result


def run_ai_research_search(
    root: str | Path,
    *,
    query: str | None = None,
    mode: str = "auto",
    max_results: int = 8,
    deep: bool = False,
    no_network: bool = False,
    fetch: bool = True,
    import_results: bool = False,
    base_url: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    project = load_project(root)
    plan = plan_ai_research_search(
        root,
        query=query or project.question,
        mode=mode,
        max_results=max_results,
        deep=deep,
        no_network=no_network,
        fetch=fetch,
        import_results=import_results,
        base_url=base_url,
    )
    resolved_query = str(plan["query"])
    resolved_url = str(plan["base_url"])
    endpoint = str(plan["endpoint"])
    payload = dict(plan["payload"])
    try:
        result = _post_json(f"{resolved_url}{endpoint}", payload, timeout=timeout_seconds)
    except Exception as exc:
        failure = {
            "ok": False,
            "base_url": resolved_url,
            "query": resolved_query,
            "payload": payload,
            "plan": plan,
            "error": str(exc),
            "next_action": _ai_research_recovery(str(exc)),
        }
        failure["bridge_run"] = create_bridge_run(
            root,
            tool="ai-research-workflow",
            action="run_ai_research_search",
            request=payload,
            endpoint=f"{resolved_url}{endpoint}",
            command=f"POST {resolved_url}{endpoint}",
            status="failed",
            error=str(exc),
            recovery_hint=failure["next_action"],
            response={"plan": plan},
        )
        return failure

    run_path = _write_tool_run(root, "ai-research-search", {"plan": plan, "request": payload, "response": result, "base_url": resolved_url})
    imported = None
    if import_results:
        imported = import_ai_research_result(root, result)
    bridge_run = create_bridge_run(
        root,
        tool="ai-research-workflow",
        action="run_ai_research_search",
        request=payload,
        endpoint=f"{resolved_url}{endpoint}",
        command=f"POST {resolved_url}{endpoint}",
        status="imported" if imported else "succeeded",
        artifact_paths=[str(run_path), *(([imported["import_path"]] if imported and imported.get("import_path") else []))],
        imported_counts=(imported or {}).get("counts", {}),
        human_review_required=bool(imported),
        response={"result": result},
    )
    return {
        "ok": True,
        "base_url": resolved_url,
        "endpoint": endpoint,
        "query": resolved_query,
        "run_path": str(run_path),
        "result": result,
        "imported": imported,
        "bridge_run": bridge_run,
    }


def run_ai_research_agent_research(
    root: str | Path,
    *,
    query: str | None = None,
    mode: str = "academic",
    max_results: int = 8,
    no_network: bool = False,
    fetch: bool = True,
    import_results: bool = False,
    base_url: str | None = None,
    timeout_seconds: int = 240,
    poll_interval_seconds: float = 1,
    auto_verify: bool = False,
) -> dict[str, Any]:
    project = load_project(root)
    resolved_query = query or project.question
    resolved_url = resolve_ai_research_url(base_url)
    endpoint = f"{resolved_url}/v1/agent/research"
    payload = {
        "query": resolved_query,
        "mode": mode,
        "max_results": int(max_results),
        "no_network": bool(no_network),
        "fetch": bool(fetch),
        "auto_verify": bool(auto_verify),
    }
    try:
        accepted = _post_json(endpoint, payload, timeout=min(int(timeout_seconds), 30))
        final_job, events = _poll_agent_job(accepted, timeout_seconds=timeout_seconds, interval_seconds=poll_interval_seconds)
    except Exception as exc:
        error = str(exc)
        bridge_run = create_bridge_run(
            root,
            tool="ai-research-workflow",
            action="deep_research_agent_contract",
            request=payload,
            endpoint=endpoint,
            command=f"POST {endpoint}",
            status="failed",
            error=error,
            recovery_hint=_ai_research_recovery(error),
            response={"accepted": locals().get("accepted", {})},
        )
        return {
            "ok": False,
            "base_url": resolved_url,
            "endpoint": "/v1/agent/research",
            "query": resolved_query,
            "payload": payload,
            "error": error,
            "failure_reason": error,
            "next_action": bridge_run["recovery_hint"],
            "job_id": str((locals().get("accepted") or {}).get("job_id") or ""),
            "run_id": "",
            "fallback_used": False,
            "bridge_run": bridge_run,
        }

    ok = str(final_job.get("status") or "") == "succeeded"
    error = str(final_job.get("error") or "")
    result_payload = final_job.get("result") if isinstance(final_job.get("result"), dict) else {}
    run_id = str(result_payload.get("run_id") or "")
    report_json: dict[str, Any] = {}
    report_fetch_error = ""
    if ok and import_results and run_id:
        try:
            report_json = fetch_ai_research_run_report(run_id, base_url=resolved_url)
        except Exception as exc:
            report_fetch_error = str(exc)
    run_path = _write_tool_run(
        root,
        "ai-research-agent-research",
        {"request": payload, "accepted": accepted, "job": final_job, "events": events, "report_json": report_json, "report_fetch_error": report_fetch_error, "base_url": resolved_url},
    )
    imported = import_ai_research_result(root, report_json or final_job, import_sources=True, import_claims=True, import_evidence=True) if import_results else None
    bridge_run = create_bridge_run(
        root,
        tool="ai-research-workflow",
        action="deep_research_agent_contract",
        request=payload,
        endpoint=endpoint,
        command=f"POST {endpoint}",
        status=("imported" if imported else "succeeded") if ok else "failed",
        artifact_paths=[str(run_path), *(([imported["import_path"]] if imported and imported.get("import_path") else []))],
        imported_counts=(imported or {}).get("counts", {}),
        error=error or report_fetch_error,
        recovery_hint="" if ok else _ai_research_recovery(error),
        human_review_required=bool(imported),
        response={"accepted": accepted, "job": final_job, "events": events},
    )
    return {
        "ok": ok,
        "base_url": resolved_url,
        "endpoint": "/v1/agent/research",
        "query": resolved_query,
        "payload": payload,
        "run_path": str(run_path),
        "accepted": accepted,
        "job": final_job,
        "events": events,
        "result": result_payload,
        "job_id": str(final_job.get("job_id") or accepted.get("job_id") or ""),
        "run_id": run_id,
        "report_json": report_json,
        "report_fetch_error": report_fetch_error,
        "imported": imported,
        "fallback_used": False,
        "failure_reason": "" if ok else error,
        "bridge_run": bridge_run,
    }


def fetch_ai_research_run_quality(run_id: str, *, base_url: str | None = None, timeout_seconds: int = 30) -> dict[str, Any]:
    resolved_url = resolve_ai_research_url(base_url)
    return _post_json(f"{resolved_url}/v1/runs/{run_id}/quality", {}, timeout=timeout_seconds)


def fetch_ai_research_run_report(run_id: str, *, base_url: str | None = None, timeout_seconds: int = 30) -> dict[str, Any]:
    resolved_url = resolve_ai_research_url(base_url)
    return _get_json(f"{resolved_url}/v1/runs/{run_id}/report.json", timeout=timeout_seconds)


def fetch_ai_research_deepen_suggestions(
    run_id: str,
    *,
    base_url: str | None = None,
    max_queries: int = 5,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    resolved_url = resolve_ai_research_url(base_url)
    return _post_json(f"{resolved_url}/v1/runs/{run_id}/deepen-claims", {"max_queries": int(max_queries)}, timeout=timeout_seconds)


def import_ai_research_result(
    root: str | Path,
    result: dict[str, Any] | str | Path,
    *,
    import_sources: bool = True,
    import_claims: bool = True,
    import_evidence: bool = True,
) -> dict[str, Any]:
    data = _load_result(result)
    source_map: dict[str, str] = {}
    imported_sources = []
    imported_claims = []
    imported_evidence = []

    existing_sources = list_records(root, "sources")
    existing_source_by_url = {str(row.get("url", "")).strip(): row for row in existing_sources if str(row.get("url", "")).strip()}
    existing_source_by_title = {str(row.get("title", "")).strip(): row for row in existing_sources if str(row.get("title", "")).strip()}

    if import_sources:
        for source in _extract_sources(data):
            local = _find_existing_source(source, existing_source_by_url, existing_source_by_title)
            if local is None:
                record = add_source(
                    root,
                    title=str(source.get("title") or source.get("url") or "Untitled source"),
                    url=str(source.get("url") or ""),
                    source_type=str(source.get("source_type") or source.get("type") or "web"),
                    quality=_quality_from_score(source),
                    notes=_source_notes(source),
                )
                local = dataclass_to_dict(record)
                existing_source_by_url[str(local.get("url", "")).strip()] = local
                existing_source_by_title[str(local.get("title", "")).strip()] = local
                imported_sources.append(local)
            _register_source_keys(source_map, source, str(local.get("id", "")))

    existing_claims = list_records(root, "claims")
    claim_by_text = {str(row.get("text", "")).strip(): row for row in existing_claims if str(row.get("text", "")).strip()}
    claim_key_map: dict[str, str] = {}
    extracted_claims = _extract_claims(data)
    evidence_claim_keys = _evidence_claim_keys(extracted_claims)
    if import_claims:
        for claim in extracted_claims:
            text = str(claim.get("text") or claim.get("claim") or "").strip()
            if not text:
                continue
            local = claim_by_text.get(text)
            if local is None:
                record = add_claim(root, text=text, notes=_claim_notes(claim))
                local = dataclass_to_dict(record)
                claim_by_text[text] = local
                imported_claims.append(local)
            _register_claim_keys(claim_key_map, claim, str(local.get("id", "")))

    if import_evidence:
        evidence_seen = {
            (str(row.get("claim_id", "")), str(row.get("source_id", "")), str(row.get("quote_or_note", "")))
            for row in list_records(root, "evidence")
        }
        for item in _extract_evidence(data):
            claim_id = _resolve_claim_id(item, claim_by_text, claim_key_map, evidence_claim_keys)
            source_id = _resolve_source_id(item, source_map, existing_source_by_url, existing_source_by_title)
            quote = str(item.get("quote_or_paraphrase") or item.get("quote_or_note") or item.get("quote") or item.get("summary") or "").strip()
            if not claim_id or not source_id or not quote:
                continue
            key = (claim_id, source_id, quote)
            if key in evidence_seen:
                continue
            record = add_evidence(
                root,
                claim_id=claim_id,
                source_id=source_id,
                quote_or_note=quote,
                relation=_relation_from_support(item),
                confidence=_confidence_from_value(item.get("confidence")),
                notes=_evidence_notes(item),
            )
            imported_evidence.append(dataclass_to_dict(record))
            evidence_seen.add(key)

    import_path = _write_tool_run(
        root,
        "ai-research-import",
        {
            "source": "ai-research-workflow",
            "source_tool": "ai-research-workflow",
            "input": data,
            "counts": {"sources": len(imported_sources), "claims": len(imported_claims), "evidence": len(imported_evidence)},
            "candidate": True,
        },
    )
    counts = {"sources": len(imported_sources), "claims": len(imported_claims), "evidence": len(imported_evidence)}
    bridge_run = create_bridge_run(
        root,
        tool="ai-research-workflow",
        action="import_ai_research_result",
        request={"result_path": str(result) if not isinstance(result, dict) else "", "import_sources": import_sources, "import_claims": import_claims, "import_evidence": import_evidence},
        status="imported",
        artifact_paths=[str(import_path), *(([str(result)] if not isinstance(result, dict) else []))],
        imported_counts=counts,
        human_review_required=True,
        response={"source_tool": "ai-research-workflow", "candidate": True},
    )
    return {
        "ok": True,
        "import_path": str(import_path),
        "imported_sources": imported_sources,
        "imported_claims": imported_claims,
        "imported_evidence": imported_evidence,
        "counts": counts,
        "bridge_run": bridge_run,
    }


def resolve_ai_research_url(base_url: str | None = None) -> str:
    if base_url:
        return base_url.rstrip("/")
    env_url = os.environ.get("AI_RESEARCH_WORKFLOW_URL")
    if env_url:
        return env_url.rstrip("/")
    registry_entry = _read_registry_entry()
    for service_file in [_service_file_from_registry(registry_entry), SERVICE_FILE]:
        if not service_file or not service_file.exists():
            continue
        try:
            data = json.loads(service_file.read_text(encoding="utf-8"))
            value = str(data.get("base_url") or "").strip()
            if value:
                return value.rstrip("/")
        except Exception:
            pass
    fallback = registry_entry.get("http", {}).get("fallback_base_url") if isinstance(registry_entry.get("http"), dict) else ""
    if fallback:
        return str(fallback).rstrip("/")
    return DEFAULT_AI_RESEARCH_URL


def _post_json(url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("ai-research-workflow returned non-object JSON")
    return parsed


def _get_json(url: str, *, timeout: int) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ai-research-workflow returned non-JSON from {url}: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("ai-research-workflow returned non-object JSON")
    return parsed


def _poll_agent_job(accepted: dict[str, Any], *, timeout_seconds: int, interval_seconds: float) -> tuple[dict[str, Any], dict[str, Any]]:
    job_id = str(accepted.get("job_id") or "")
    links = accepted.get("links") if isinstance(accepted.get("links"), dict) else {}
    job_url = str(links.get("job") or "")
    events_url = str(links.get("events") or "")
    if not job_id or not job_url or not events_url:
        raise RuntimeError("ai-research-workflow agent contract response is missing job_id or polling links")
    deadline = time.monotonic() + timeout_seconds
    final_job: dict[str, Any] = {}
    while True:
        final_job = _get_json(job_url, timeout=min(int(timeout_seconds), 30))
        status = str(final_job.get("status") or "")
        if status in {"succeeded", "failed"}:
            events = _get_json(events_url, timeout=min(int(timeout_seconds), 30))
            return final_job, events
        if time.monotonic() >= deadline:
            events = _get_json(events_url, timeout=min(int(timeout_seconds), 30))
            raise RuntimeError(f"ai-research-workflow agent job timed out: {job_id}; recent_events={events.get('events', [])[-5:]}")
        time.sleep(interval_seconds)


def _read_service_config() -> dict[str, Any]:
    registry_entry = _read_registry_entry()
    for service_file in [_service_file_from_registry(registry_entry), SERVICE_FILE]:
        if not service_file or not service_file.exists():
            continue
        try:
            data = json.loads(service_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _read_registry_entry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else data
    entry = tools.get("ai-research-workflow") if isinstance(tools, dict) else None
    return entry if isinstance(entry, dict) else {}


def _service_file_from_registry(entry: dict[str, Any]) -> Path | None:
    value = str(entry.get("service_file") or "").strip()
    return Path(value) if value else None


def _ai_research_recovery(error: str) -> str:
    text = str(error or "").lower()
    if "connection refused" in text or "actively refused" in text or "timed out" in text or "winerror 10061" in text:
        return "ai-research-workflow 服务未启动或端口不可达：先检查 registry/service.json 的 base_url，再启动该工具的 HTTP 服务。"
    if "non-json" in text or "json" in text:
        return "ai-research-workflow 返回了非 JSON：检查服务是否指向了正确端口，或查看服务日志。"
    if "sources" in text or "claims" in text or "evidence" in text:
        return "搜索结果缺少 sources/claims/evidence：保留原始结果，改用本地 result JSON 导入或调整搜索模式后重试。"
    return "检查 ai-research-workflow 是否启动、base_url/端口是否正确，并确认 /v1/health、/v1/capabilities、/v1/discovery 可访问。"


def _write_tool_run(root: str | Path, prefix: str, payload: dict[str, Any]) -> Path:
    paths = ensure_project_dirs(root)
    run_dir = paths["root"] / "tool-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{prefix}-{now_iso().replace(':', '-')}.json"
    write_json(path, payload)
    return path


def _load_result(result: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    path = Path(result)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("ai-research result must be a JSON object")
    return data


def _extract_sources(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("sources") or data.get("source_candidates") or []
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    return []


def _extract_claims(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("claims") or data.get("claim_table") or data.get("claim_candidates") or []
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    return []


def _extract_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("evidence") or data.get("evidence_candidates") or []
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    return []


def _find_existing_source(source: dict[str, Any], by_url: dict[str, dict[str, Any]], by_title: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    url = str(source.get("url") or "").strip()
    title = str(source.get("title") or "").strip()
    if url and url in by_url:
        return by_url[url]
    if title and title in by_title:
        return by_title[title]
    return None


def _register_source_keys(source_map: dict[str, str], source: dict[str, Any], local_id: str) -> None:
    for key in ("id", "source_id", "url", "title"):
        value = str(source.get(key) or "").strip()
        if value:
            source_map[value] = local_id


def _resolve_source_id(item: dict[str, Any], source_map: dict[str, str], by_url: dict[str, dict[str, Any]], by_title: dict[str, dict[str, Any]]) -> str:
    for key in ("source_id", "source", "url", "title"):
        value = str(item.get(key) or "").strip()
        if value in source_map:
            return source_map[value]
        if value in by_url:
            return str(by_url[value].get("id", ""))
        if value in by_title:
            return str(by_title[value].get("id", ""))
    return ""


def _register_claim_keys(claim_key_map: dict[str, str], claim: dict[str, Any], local_id: str) -> None:
    for key in ("id", "claim_id", "text", "claim"):
        value = str(claim.get(key) or "").strip()
        if value:
            claim_key_map[value] = local_id


def _evidence_claim_keys(claims: list[dict[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for claim in claims:
        claim_key = str(claim.get("id") or claim.get("text") or claim.get("claim") or "").strip()
        if not claim_key:
            continue
        for evidence_id in claim.get("evidence_ids") or []:
            value = str(evidence_id or "").strip()
            if value:
                output[value] = claim_key
    return output


def _resolve_claim_id(
    item: dict[str, Any],
    claim_by_text: dict[str, dict[str, Any]],
    claim_key_map: dict[str, str],
    evidence_claim_keys: dict[str, str],
) -> str:
    for key in ("claim_text", "claim", "text", "claim_relevance"):
        value = str(item.get(key) or "").strip()
        if value in claim_by_text:
            return str(claim_by_text[value].get("id", ""))
        if value in claim_key_map:
            return claim_key_map[value]
    claim_id = str(item.get("claim_id") or "").strip()
    if claim_id in claim_key_map:
        return claim_key_map[claim_id]
    evidence_id = str(item.get("id") or item.get("evidence_id") or "").strip()
    claim_key = evidence_claim_keys.get(evidence_id, "")
    if claim_key in claim_key_map:
        return claim_key_map[claim_key]
    if claim_key in claim_by_text:
        return str(claim_by_text[claim_key].get("id", ""))
    return ""


def _quality_from_score(source: dict[str, Any]) -> str:
    score = source.get("quality_score")
    try:
        value = float(score)
    except (TypeError, ValueError):
        return str(source.get("quality") or "unknown")
    if value >= 70:
        return "good"
    if value >= 40:
        return "mixed"
    return "poor"


def _source_notes(source: dict[str, Any]) -> str:
    parts = []
    for key in ("snippet", "summary", "publisher", "verification_status", "published_at", "retrieved_at", "local_path", "source_path", "artifact_sha256", "content_hash", "search_engine"):
        value = source.get(key)
        if value:
            parts.append(f"{key}: {value}")
    reasons = source.get("quality_reasons")
    if reasons:
        parts.append(f"quality_reasons: {reasons}")
    return "\n".join(parts)


def _claim_notes(claim: dict[str, Any]) -> str:
    parts = ["由 ai-research-workflow 导入，需继续审核。"]
    for key in ("claim_type", "risk_level", "verdict", "confidence"):
        value = claim.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _relation_from_support(item: dict[str, Any]) -> str:
    value = str(item.get("support_direction") or item.get("relation") or "").lower()
    if value in {"supports", "support", "supported", "for"}:
        return "supports"
    if value in {"contradicts", "contradict", "contradicted", "against"}:
        return "contradicts"
    if value in {"context", "partial", "mixed"}:
        return "context"
    return "unknown"


def _confidence_from_value(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"high", "medium", "low", "unknown"}:
        return text
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _evidence_notes(item: dict[str, Any]) -> str:
    parts = ["由 ai-research-workflow 导入，默认仍是 candidate，需人工审核。"]
    for key in ("claim_relevance", "support_direction", "source_id", "verification_status", "observed_at", "retrieved_at", "source_path", "artifact_sha256", "content_hash", "extraction_method"):
        value = item.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)
