from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge_runs import create_bridge_run
from .models import dataclass_to_dict, now_iso
from .orchestrator import add_source, list_records
from .storage import ensure_project_dirs, load_project, write_json


DEFAULT_VANE_PERPLEXICA_URL = "http://127.0.0.1:3000"


def vane_perplexica_status(base_url: str | None = None) -> dict[str, Any]:
    resolved_url = resolve_vane_perplexica_url(base_url)
    try:
        providers = _get_json(f"{resolved_url}/api/providers", timeout=10)
        ok = True
        error = ""
    except Exception as exc:
        providers = {}
        ok = False
        error = str(exc)
    return {
        "ok": ok,
        "schema": "question_research_vane_perplexica_status.v1",
        "tool": "vane-perplexica",
        "base_url": resolved_url,
        "providers": providers,
        "error": error,
        "recovery_hint": "" if ok else _vane_recovery(error),
        "delegation_boundary": "Vane/Perplexica is used only as an optional candidate-source search bridge; question-research-poc keeps review gates and does not treat its answer as verified evidence.",
    }


def plan_vane_perplexica_search(
    root: str | Path,
    *,
    query: str | None = None,
    sources: str | list[str] | None = None,
    optimization_mode: str = "balanced",
    base_url: str | None = None,
    chat_provider_id: str = "",
    chat_model_key: str = "",
    embedding_provider_id: str = "",
    embedding_model_key: str = "",
    system_instructions: str = "",
    import_results: bool = False,
) -> dict[str, Any]:
    project = load_project(root)
    resolved_query = query or project.question
    resolved_url = resolve_vane_perplexica_url(base_url)
    source_list = _source_list(sources)
    status = vane_perplexica_status(resolved_url)
    model_selection = _select_models(
        status.get("providers") if isinstance(status.get("providers"), dict) else {},
        chat_provider_id=chat_provider_id,
        chat_model_key=chat_model_key,
        embedding_provider_id=embedding_provider_id,
        embedding_model_key=embedding_model_key,
    )
    payload = {
        "chatModel": model_selection["chat_model"],
        "embeddingModel": model_selection["embedding_model"],
        "optimizationMode": _optimization_mode(optimization_mode),
        "sources": source_list,
        "query": resolved_query,
        "history": [],
        "systemInstructions": system_instructions,
        "stream": False,
    }
    ok = bool(status.get("ok")) and bool(model_selection["ok"])
    result = {
        "ok": ok,
        "tool": "vane-perplexica",
        "base_url": resolved_url,
        "endpoint": "/api/search",
        "providers_endpoint": "/api/providers",
        "method": "POST",
        "query": resolved_query,
        "payload": payload,
        "import_results": bool(import_results),
        "expected_outputs": ["message_candidate_context", "candidate_sources", "raw_response"],
        "status": status,
        "model_selection": model_selection,
        "delegation_boundary": "question-research-poc only dispatches Vane/Perplexica search, saves raw artifacts, and optionally imports candidate sources; it does not import verified evidence or source quality.",
        "failure_next_action": "" if ok else _vane_recovery(status.get("error") or model_selection.get("error") or ""),
    }
    bridge_run = create_bridge_run(
        root,
        tool="vane-perplexica",
        action="plan_vane_perplexica_search",
        request=payload,
        endpoint=f"{resolved_url}/api/search",
        command=f"POST {resolved_url}/api/search",
        status="planned" if ok else "needs_human",
        error="" if ok else result["failure_next_action"],
        recovery_hint=result["failure_next_action"],
        human_review_required=not ok,
        response={"plan": {key: value for key, value in result.items() if key != "bridge_run"}},
    )
    result["bridge_run"] = bridge_run
    return result


def run_vane_perplexica_search(
    root: str | Path,
    *,
    query: str | None = None,
    sources: str | list[str] | None = None,
    optimization_mode: str = "balanced",
    base_url: str | None = None,
    chat_provider_id: str = "",
    chat_model_key: str = "",
    embedding_provider_id: str = "",
    embedding_model_key: str = "",
    system_instructions: str = "",
    import_results: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    plan = plan_vane_perplexica_search(
        root,
        query=query,
        sources=sources,
        optimization_mode=optimization_mode,
        base_url=base_url,
        chat_provider_id=chat_provider_id,
        chat_model_key=chat_model_key,
        embedding_provider_id=embedding_provider_id,
        embedding_model_key=embedding_model_key,
        system_instructions=system_instructions,
        import_results=import_results,
    )
    if not plan.get("ok"):
        return {
            "ok": False,
            "plan": plan,
            "base_url": plan.get("base_url", ""),
            "error": plan.get("failure_next_action", "Vane/Perplexica search is not ready."),
            "recovery_hint": plan.get("failure_next_action", ""),
            "bridge_run": create_bridge_run(
                root,
                tool="vane-perplexica",
                action="run_vane_perplexica_search",
                request=plan.get("payload", {}),
                endpoint=f"{plan.get('base_url', '')}/api/search",
                command=f"POST {plan.get('base_url', '')}/api/search",
                status="needs_human",
                error=plan.get("failure_next_action", ""),
                recovery_hint=plan.get("failure_next_action", ""),
                human_review_required=True,
                response={"plan": plan},
            ),
        }

    resolved_url = str(plan["base_url"])
    payload = dict(plan["payload"])
    try:
        response = _post_json(f"{resolved_url}/api/search", payload, timeout=timeout_seconds)
    except Exception as exc:
        bridge_run = create_bridge_run(
            root,
            tool="vane-perplexica",
            action="run_vane_perplexica_search",
            request=payload,
            endpoint=f"{resolved_url}/api/search",
            command=f"POST {resolved_url}/api/search",
            status="failed",
            error=str(exc),
            recovery_hint=_vane_recovery(str(exc)),
            human_review_required=True,
            response={"plan": plan},
        )
        return {
            "ok": False,
            "base_url": resolved_url,
            "payload": payload,
            "plan": plan,
            "error": str(exc),
            "recovery_hint": bridge_run["recovery_hint"],
            "bridge_run": bridge_run,
        }

    artifacts = _write_vane_artifacts(root, plan=plan, response=response)
    imported = import_vane_perplexica_result(root, response, raw_response_path=artifacts["json_path"]) if import_results else None
    bridge_run = create_bridge_run(
        root,
        tool="vane-perplexica",
        action="run_vane_perplexica_search",
        request=payload,
        endpoint=f"{resolved_url}/api/search",
        command=f"POST {resolved_url}/api/search",
        status="imported" if imported else "succeeded",
        artifact_paths=[artifacts["json_path"], artifacts["markdown_path"], *(([imported["import_path"]] if imported else []))],
        imported_counts=(imported or {}).get("counts", {}),
        human_review_required=bool(imported),
        response={"result": response, "candidate_context_path": artifacts["markdown_path"]},
    )
    return {
        "ok": True,
        "base_url": resolved_url,
        "query": plan["query"],
        "result": response,
        "json_path": artifacts["json_path"],
        "markdown_path": artifacts["markdown_path"],
        "imported": imported,
        "bridge_run": bridge_run,
    }


def import_vane_perplexica_result(
    root: str | Path,
    result: dict[str, Any] | str | Path,
    *,
    raw_response_path: str = "",
    import_sources: bool = True,
) -> dict[str, Any]:
    data = _load_result(result)
    imported_sources = []
    existing_sources = list_records(root, "sources")
    existing_source_by_url = {str(row.get("url", "")).strip(): row for row in existing_sources if str(row.get("url", "")).strip()}
    existing_source_by_title = {str(row.get("title", "")).strip(): row for row in existing_sources if str(row.get("title", "")).strip()}
    if import_sources:
        for source in _extract_vane_sources(data):
            local = _find_existing_source(source, existing_source_by_url, existing_source_by_title)
            if local is not None:
                continue
            record = add_source(
                root,
                title=str(source.get("title") or source.get("url") or "Vane/Perplexica source"),
                url=str(source.get("url") or ""),
                source_type="web",
                quality="unknown",
                notes=_source_notes(source, raw_response_path=raw_response_path),
            )
            local = dataclass_to_dict(record)
            existing_source_by_url[str(local.get("url", "")).strip()] = local
            existing_source_by_title[str(local.get("title", "")).strip()] = local
            imported_sources.append(local)
    import_path = _write_tool_run(
        root,
        "vane-perplexica-import",
        {
            "source": "vane-perplexica",
            "source_tool": "vane-perplexica",
            "input": data,
            "raw_response_path": raw_response_path,
            "candidate": True,
            "counts": {"sources": len(imported_sources), "claims": 0, "evidence": 0},
            "boundary": "Imported rows are candidate sources only. Vane/Perplexica message is candidate context and no evidence is verified.",
        },
    )
    counts = {"sources": len(imported_sources), "claims": 0, "evidence": 0}
    bridge_run = create_bridge_run(
        root,
        tool="vane-perplexica",
        action="import_vane_perplexica_result",
        request={"result_path": str(result) if not isinstance(result, dict) else "", "import_sources": import_sources},
        status="imported",
        artifact_paths=[str(import_path), raw_response_path],
        imported_counts=counts,
        human_review_required=True,
        response={"source_tool": "vane-perplexica", "candidate": True, "message_imported_as": "candidate_context_only"},
    )
    return {
        "ok": True,
        "import_path": str(import_path),
        "imported_sources": imported_sources,
        "imported_claims": [],
        "imported_evidence": [],
        "counts": counts,
        "bridge_run": bridge_run,
    }


def resolve_vane_perplexica_url(base_url: str | None = None) -> str:
    if base_url:
        return base_url.rstrip("/")
    for name in ("VANE_PERPLEXICA_URL", "VANE_URL", "PERPLEXICA_URL"):
        value = os.environ.get(name)
        if value:
            return value.rstrip("/")
    return DEFAULT_VANE_PERPLEXICA_URL


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
        raise RuntimeError(f"Vane/Perplexica returned non-JSON from {url}: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Vane/Perplexica returned non-object JSON")
    return parsed


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
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vane/Perplexica returned non-JSON from {url}: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Vane/Perplexica returned non-object JSON")
    return parsed


def _select_models(
    providers_payload: dict[str, Any],
    *,
    chat_provider_id: str,
    chat_model_key: str,
    embedding_provider_id: str,
    embedding_model_key: str,
) -> dict[str, Any]:
    if chat_provider_id and chat_model_key and embedding_provider_id and embedding_model_key:
        return {
            "ok": True,
            "chat_model": {"providerId": chat_provider_id, "key": chat_model_key},
            "embedding_model": {"providerId": embedding_provider_id, "key": embedding_model_key},
            "missing": [],
            "error": "",
        }
    providers = providers_payload.get("providers")
    if not isinstance(providers, list):
        providers = []
    chat_model = _explicit_or_first_model(providers, provider_id=chat_provider_id, model_key=chat_model_key, model_field="chatModels")
    embedding_model = _explicit_or_first_model(providers, provider_id=embedding_provider_id, model_key=embedding_model_key, model_field="embeddingModels")
    missing = []
    if not chat_model:
        missing.append("chatModel")
    if not embedding_model:
        missing.append("embeddingModel")
    return {
        "ok": not missing,
        "chat_model": chat_model or {"providerId": chat_provider_id, "key": chat_model_key},
        "embedding_model": embedding_model or {"providerId": embedding_provider_id, "key": embedding_model_key},
        "missing": missing,
        "error": "" if not missing else f"missing Vane/Perplexica model selection: {', '.join(missing)}",
    }


def _explicit_or_first_model(providers: list[Any], *, provider_id: str, model_key: str, model_field: str) -> dict[str, str] | None:
    provider_id = str(provider_id or "").strip()
    model_key = str(model_key or "").strip()
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        current_provider_id = str(provider.get("id") or "")
        models = provider.get(model_field)
        if not isinstance(models, list):
            models = []
        if provider_id and current_provider_id != provider_id:
            continue
        for model in models:
            if not isinstance(model, dict):
                continue
            key = str(model.get("key") or "")
            if model_key and key != model_key:
                continue
            if current_provider_id and key:
                return {"providerId": current_provider_id, "key": key}
        if provider_id:
            return None
    return None


def _source_list(value: str | list[str] | None) -> list[str]:
    allowed = {"web", "academic", "discussions"}
    if value is None:
        return ["web"]
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",")]
    else:
        raw = [str(item).strip() for item in value]
    cleaned = [item for item in raw if item in allowed]
    return cleaned or ["web"]


def _optimization_mode(value: str) -> str:
    text = str(value or "").strip()
    return text if text in {"speed", "balanced", "quality"} else "balanced"


def _write_vane_artifacts(root: str | Path, *, plan: dict[str, Any], response: dict[str, Any]) -> dict[str, str]:
    run_path = _write_tool_run(
        root,
        "vane-perplexica-search",
        {
            "source": "vane-perplexica",
            "source_tool": "vane-perplexica",
            "plan": plan,
            "request": plan.get("payload", {}),
            "response": response,
            "candidate": True,
        },
    )
    markdown_path = run_path.with_suffix(".md")
    markdown_path.write_text(_render_markdown(plan, response), encoding="utf-8")
    return {"json_path": str(run_path), "markdown_path": str(markdown_path)}


def _render_markdown(plan: dict[str, Any], response: dict[str, Any]) -> str:
    lines = [
        "# Vane/Perplexica Candidate Search",
        "",
        f"- Query: {plan.get('query', '')}",
        f"- Base URL: {plan.get('base_url', '')}",
        f"- Sources mode: {', '.join(plan.get('payload', {}).get('sources', []))}",
        f"- Optimization: {plan.get('payload', {}).get('optimizationMode', '')}",
        "- Boundary: message is candidate context only; sources are candidate sources; no evidence is verified.",
        "",
        "## Candidate Context",
        "",
        str(response.get("message") or "").strip() or "_No message returned._",
        "",
        "## Candidate Sources",
        "",
    ]
    sources = _extract_vane_sources(response)
    if not sources:
        lines.append("- No sources returned.")
    for index, source in enumerate(sources, start=1):
        title = str(source.get("title") or source.get("url") or f"Source {index}")
        url = str(source.get("url") or "")
        content = str(source.get("content") or "").strip()
        if url:
            lines.append(f"{index}. [{title}]({url})")
        else:
            lines.append(f"{index}. {title}")
        if content:
            lines.append(f"   - Candidate snippet: {content}")
    lines.append("")
    return "\n".join(lines)


def _extract_vane_sources(data: dict[str, Any]) -> list[dict[str, Any]]:
    sources = data.get("sources")
    if not isinstance(sources, list):
        return []
    rows = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        rows.append(
            {
                "title": str(metadata.get("title") or item.get("title") or metadata.get("url") or item.get("url") or "").strip(),
                "url": str(metadata.get("url") or item.get("url") or "").strip(),
                "content": str(item.get("content") or item.get("snippet") or "").strip(),
                "raw": item,
            }
        )
    return [row for row in rows if row.get("url") or row.get("title")]


def _find_existing_source(source: dict[str, Any], by_url: dict[str, dict[str, Any]], by_title: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    url = str(source.get("url") or "").strip()
    title = str(source.get("title") or "").strip()
    if url and url in by_url:
        return by_url[url]
    if title and title in by_title:
        return by_title[title]
    return None


def _source_notes(source: dict[str, Any], *, raw_response_path: str) -> str:
    snippet = str(source.get("content") or "").strip()
    parts = [
        "Candidate source imported from Vane/Perplexica /api/search.",
        "Source quality remains unknown until human review.",
        "No verified evidence was generated from this import.",
    ]
    if raw_response_path:
        parts.append(f"Raw response: {raw_response_path}")
    if snippet:
        parts.append(f"Candidate snippet: {snippet[:500]}")
    return " ".join(parts)


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
        raise ValueError("Vane/Perplexica result must be a JSON object")
    return data


def _vane_recovery(error: str) -> str:
    text = str(error or "").lower()
    if "connection refused" in text or "actively refused" in text or "timed out" in text or "winerror 10061" in text:
        return "Vane/Perplexica 服务未启动或端口不可达：先启动该 Next.js 服务，或通过 VANE_PERPLEXICA_URL/base_url 指向正确地址。"
    if "providers" in text or "chatmodel" in text or "embeddingmodel" in text or "model" in text:
        return "Vane/Perplexica 缺少可用 provider/model：先打开 /api/providers，配置 chatModel 和 embeddingModel 后重试。"
    if "non-json" in text or "json" in text:
        return "Vane/Perplexica 返回了非 JSON：检查 base_url 是否指向正确服务，而不是普通网页。"
    return "检查 Vane/Perplexica 服务、/api/providers、/api/search、provider/model 配置和 SearXNG 后重试。"
