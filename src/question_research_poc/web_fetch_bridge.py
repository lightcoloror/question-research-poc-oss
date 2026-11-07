from __future__ import annotations

import json
import os
import subprocess
from hashlib import sha1
from pathlib import Path
from typing import Any

from .bridge_runs import create_bridge_run
from .models import dataclass_to_dict, now_iso
from .orchestrator import add_evidence, add_source, list_records
from .runtime_paths import web_content_fetcher_root
from .storage import ensure_project_dirs, write_json


WEB_CONTENT_FETCHER_ROOT = web_content_fetcher_root()


def plan_fetch_source_content(
    root: str | Path,
    *,
    source_id: str | None = None,
    url: str | None = None,
    title: str | None = None,
    claim_id: str | None = None,
    fetch_profile: str = "generic",
    backend: str = "auto",
    extractor: str = "auto",
    use_browser: bool = False,
    include_raw: bool = False,
    timeout_seconds: int = 30,
    import_source: bool = True,
    create_candidate_evidence: bool = False,
) -> dict[str, Any]:
    paths = ensure_project_dirs(root)
    source = _resolve_source_for_plan(root, source_id=source_id, url=url, title=title, import_source=import_source)
    target_url = str(source.get("url") or url or "").strip()
    command = _fetch_command_args(
        target_url or "<missing-url>",
        fetch_profile=fetch_profile,
        backend=backend,
        extractor=extractor,
        use_browser=use_browser,
        include_raw=include_raw,
        timeout_seconds=timeout_seconds,
    )
    slug = _slug(source.get("id") or target_url or title or "source")
    result = {
        "ok": bool(target_url),
        "tool": "web-content-fetcher",
        "tool_root": str(WEB_CONTENT_FETCHER_ROOT),
        "source": source,
        "url": target_url,
        "claim_id": claim_id or "",
        "command": command,
        "cwd": str(WEB_CONTENT_FETCHER_ROOT),
        "outputs": {
            "json_path": str(paths["root"] / "fetched-sources" / f"{slug}.json"),
            "markdown_path": str(paths["root"] / "fetched-sources" / f"{slug}.md"),
            "tool_run_prefix": str(paths["root"] / "tool-runs" / "web-content-fetch-<timestamp>.json"),
        },
        "create_candidate_evidence": bool(create_candidate_evidence),
        "delegation_boundary": "question-research-poc only plans, dispatches, stores fetched artifacts, and creates candidate evidence; web-content-fetcher performs webpage fetching/extraction.",
        "failure_next_action": "如果 URL 缺失，先给 source 填 URL；如果工具不可用，先检查 web-content-fetcher 本地安装和配置。",
    }
    result["bridge_run"] = create_bridge_run(
        root,
        tool="web-content-fetcher",
        action="plan_fetch_source_content",
        request={
            "source_id": source_id or "",
            "url": target_url,
            "claim_id": claim_id or "",
            "fetch_profile": fetch_profile,
            "backend": backend,
            "extractor": extractor,
            "use_browser": use_browser,
            "include_raw": include_raw,
        },
        command=command,
        status="planned" if target_url else "needs_human",
        artifact_paths=list(result["outputs"].values()),
        error="" if target_url else "missing url",
        recovery_hint=result["failure_next_action"],
        human_review_required=not bool(target_url),
        response={"plan": {key: value for key, value in result.items() if key != "bridge_run"}},
    )
    return result


def fetch_source_content(
    root: str | Path,
    *,
    source_id: str | None = None,
    url: str | None = None,
    title: str | None = None,
    claim_id: str | None = None,
    fetch_profile: str = "generic",
    backend: str = "auto",
    extractor: str = "auto",
    use_browser: bool = False,
    include_raw: bool = False,
    timeout_seconds: int = 30,
    import_source: bool = True,
    create_candidate_evidence: bool = False,
) -> dict[str, Any]:
    paths = ensure_project_dirs(root)
    source = _resolve_or_create_source(root, source_id=source_id, url=url, title=title, import_source=import_source)
    target_url = str(source.get("url") or url or "").strip()
    if not target_url:
        raise ValueError("source_id must point to a source with url, or url must be provided")
    plan = plan_fetch_source_content(
        root,
        source_id=source_id,
        url=url,
        title=title,
        claim_id=claim_id,
        fetch_profile=fetch_profile,
        backend=backend,
        extractor=extractor,
        use_browser=use_browser,
        include_raw=include_raw,
        timeout_seconds=timeout_seconds,
        import_source=import_source,
        create_candidate_evidence=create_candidate_evidence,
    )

    try:
        result = _run_fetch_command(
            target_url,
            fetch_profile=fetch_profile,
            backend=backend,
            extractor=extractor,
            use_browser=use_browser,
            include_raw=include_raw,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        bridge_run = create_bridge_run(
            root,
            tool="web-content-fetcher",
            action="fetch_source_content",
            request=plan.get("source", {}) | {
                "source_id": source.get("id") or source_id or "",
                "url": target_url,
                "claim_id": claim_id or "",
                "fetch_profile": fetch_profile,
                "backend": backend,
                "extractor": extractor,
                "use_browser": use_browser,
                "include_raw": include_raw,
            },
            command=plan.get("command", []),
            status="failed",
            error=str(exc),
            recovery_hint=_fetch_recovery(str(exc)),
            response={"plan": plan},
        )
        raise RuntimeError(f"{exc}; recovery: {bridge_run['recovery_hint']}") from exc
    fetched_dir = paths["root"] / "fetched-sources"
    fetched_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(source.get("id") or target_url)
    json_path = fetched_dir / f"{slug}.json"
    md_path = fetched_dir / f"{slug}.md"
    write_json(json_path, result)
    md_path.write_text(_render_fetched_markdown(source, result), encoding="utf-8")

    evidence_rows = []
    if create_candidate_evidence and claim_id:
        claim = _find_record(list_records(root, "claims"), claim_id)
        if claim:
            for excerpt in _candidate_excerpts(str(result.get("text") or result.get("extracted_text") or result.get("markdown") or ""), str(claim.get("text") or "")):
                evidence = add_evidence(
                    root,
                    claim_id=claim_id,
                    source_id=str(source.get("id")),
                    quote_or_note=excerpt,
                    relation="unknown",
                    confidence="low",
                    notes=f"由 web-content-fetcher 抓取正文后按关键词生成的候选摘录。抓取文件：{md_path}",
                )
                evidence_rows.append(dataclass_to_dict(evidence))

    run_path = paths["root"] / "tool-runs" / f"web-content-fetch-{now_iso().replace(':', '-')}.json"
    legacy_payload = {
        "source": "web-content-fetcher",
        "source_tool": "web-content-fetcher",
        "plan": plan,
        "request": {
            "source_id": source.get("id"),
            "url": target_url,
            "claim_id": claim_id,
            "fetch_profile": fetch_profile,
            "backend": backend,
            "extractor": extractor,
            "use_browser": use_browser,
            "include_raw": include_raw,
        },
        "result_path": str(json_path),
        "markdown_path": str(md_path),
        "candidate_evidence": evidence_rows,
        "artifact_paths": _external_artifact_paths(result),
    }
    write_json(
        run_path,
        legacy_payload,
    )
    bridge_run = create_bridge_run(
        root,
        tool="web-content-fetcher",
        action="fetch_source_content",
        request=legacy_payload["request"],
        command=plan.get("command", []),
        status="imported" if evidence_rows or import_source else "succeeded",
        artifact_paths=[str(json_path), str(md_path), str(run_path), *_external_artifact_paths(result)],
        imported_counts={"sources": 1 if import_source else 0, "evidence": len(evidence_rows)},
        human_review_required=bool(evidence_rows),
        response={"result": result, "candidate_evidence_count": len(evidence_rows)},
    )
    return {
        "ok": str(result.get("status") or "ok") == "ok",
        "source": source,
        "result": result,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "run_path": str(run_path),
        "candidate_evidence": evidence_rows,
        "bridge_run": bridge_run,
    }


def _resolve_or_create_source(
    root: str | Path,
    *,
    source_id: str | None,
    url: str | None,
    title: str | None,
    import_source: bool,
) -> dict[str, Any]:
    sources = list_records(root, "sources")
    if source_id:
        source = _find_record(sources, source_id)
        if not source:
            raise ValueError(f"source not found: {source_id}")
        return source
    target_url = str(url or "").strip()
    if target_url:
        for source in sources:
            if str(source.get("url") or "").strip() == target_url:
                return source
    if not import_source:
        return {"id": "", "title": title or target_url, "url": target_url, "source_type": "web", "quality": "unknown"}
    record = add_source(root, title=title or target_url or "Fetched web source", url=target_url, source_type="web", notes="由 web-content-fetcher 抓取入口自动创建。")
    return dataclass_to_dict(record)


def _resolve_source_for_plan(
    root: str | Path,
    *,
    source_id: str | None,
    url: str | None,
    title: str | None,
    import_source: bool,
) -> dict[str, Any]:
    sources = list_records(root, "sources")
    if source_id:
        source = _find_record(sources, source_id)
        if source:
            return source
        return {"id": source_id, "title": title or source_id, "url": url or "", "source_type": "web", "quality": "unknown", "missing": True}
    target_url = str(url or "").strip()
    if target_url:
        for source in sources:
            if str(source.get("url") or "").strip() == target_url:
                return source
    return {"id": "", "title": title or target_url or "Fetched web source", "url": target_url, "source_type": "web", "quality": "unknown", "would_import_source": bool(import_source)}


def _run_fetch_command(
    url: str,
    *,
    fetch_profile: str,
    backend: str,
    extractor: str,
    use_browser: bool,
    include_raw: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not WEB_CONTENT_FETCHER_ROOT.exists():
        raise FileNotFoundError(f"web-content-fetcher not found: {WEB_CONTENT_FETCHER_ROOT}")
    args = _fetch_command_args(
        url,
        fetch_profile=fetch_profile,
        backend=backend,
        extractor=extractor,
        use_browser=use_browser,
        include_raw=include_raw,
        timeout_seconds=timeout_seconds,
    )
    completed = subprocess.run(
        args,
        cwd=WEB_CONTENT_FETCHER_ROOT,
        env={**os.environ, "PYTHONPATH": str(WEB_CONTENT_FETCHER_ROOT)},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=max(timeout_seconds + 20, 60),
        check=False,
    )
    if completed.returncode not in {0, 2}:
        raise RuntimeError(f"web-content-fetcher failed: {completed.stderr or completed.stdout}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"web-content-fetcher returned non-JSON output: {completed.stdout[:500]}") from exc
    if not isinstance(data, dict):
        raise ValueError("web-content-fetcher output must be a JSON object")
    return data


def _fetch_command_args(
    url: str,
    *,
    fetch_profile: str,
    backend: str,
    extractor: str,
    use_browser: bool,
    include_raw: bool,
    timeout_seconds: int,
) -> list[str]:
    args = [
        "python",
        "-m",
        "web_content_fetcher",
        "fetch",
        url,
        "--fetch-profile",
        fetch_profile,
        "--backend",
        backend,
        "--extractor",
        extractor,
        "--timeout",
        str(timeout_seconds),
        "--format",
        "json",
    ]
    if use_browser:
        args.append("--browser")
    if include_raw:
        args.append("--include-raw")
    return args


def _render_fetched_markdown(source: dict[str, Any], result: dict[str, Any]) -> str:
    text = str(result.get("text") or result.get("extracted_text") or result.get("markdown") or "")
    lines = [
        "---",
        "type: note",
        f'title: "{source.get("title") or result.get("title") or result.get("final_url") or "fetched source"}"',
        "tags: [ai-research, fetched-source]",
        "status: candidate",
        f"created: {now_iso()}",
        "---",
        "",
        f"# {source.get('title') or result.get('title') or 'Fetched source'}",
        "",
        f"- 来源 ID：`{source.get('id', '')}`",
        f"- 请求 URL：{result.get('requested_url') or source.get('url') or ''}",
        f"- 最终 URL：{result.get('final_url') or ''}",
        f"- 抓取状态：`{result.get('status', '')}`",
        f"- 抽取方式：`{result.get('extractor', '')}` / `{result.get('transport', '')}`",
        "",
        "## 正文",
        "",
        text.strip() or "(未抽取到正文)",
        "",
    ]
    errors = result.get("errors")
    if errors:
        lines.extend(["## 抓取错误", "", str(errors), ""])
    return "\n".join(lines).rstrip() + "\n"


def _external_artifact_paths(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("archive_path", "raw_path", "extracted_path", "raw_html_path", "markdown_path", "screenshot_path"):
        value = result.get(key)
        if value:
            paths.append(str(value))
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        for value in artifacts.values():
            if value:
                paths.append(str(value))
    if isinstance(artifacts, list):
        paths.extend(str(value) for value in artifacts if value)
    return sorted(set(paths))


def _fetch_recovery(error: str) -> str:
    text = str(error or "").lower()
    if "not found" in text:
        return "web-content-fetcher 本地路径不可用：先检查 tool-registry.json 中的路径或重新安装该工具。"
    if "non-json" in text or "json" in text:
        return "web-content-fetcher 返回了非 JSON：检查 CLI 参数、工具版本，必要时用命令行单独运行抓取命令。"
    if "timeout" in text:
        return "网页抓取超时：提高 timeout、启用 browser 模式，或先用浏览器确认该 URL 可访问。"
    return "检查 URL、web-content-fetcher 安装、网络/浏览器抓取配置；本项目只保留失败 run 和 recovery，不自动改写来源质量。"


def _candidate_excerpts(text: str, claim_text: str, *, limit: int = 3) -> list[str]:
    if not text.strip() or not claim_text.strip():
        return []
    terms = [term for term in _tokenize_claim(claim_text) if len(term) >= 2]
    chunks = _split_chunks(text)
    scored = []
    for chunk in chunks:
        score = sum(1 for term in terms if term in chunk)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return [chunk for _, chunk in scored[:limit]]


def _tokenize_claim(text: str) -> list[str]:
    separators = " ，。！？；：、（）()[]【】<>《》\n\t"
    tokens = []
    current = []
    for char in text:
        if char in separators:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _split_chunks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_chunks = []
    for paragraph in normalized.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= 280:
            raw_chunks.append(paragraph)
        else:
            for index in range(0, len(paragraph), 240):
                raw_chunks.append(paragraph[index : index + 280].strip())
    return [chunk for chunk in raw_chunks if chunk]


def _find_record(rows: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("id") == record_id:
            return row
    return None


def _slug(value: Any) -> str:
    text = str(value or "source")
    digest = sha1(text.encode("utf-8")).hexdigest()[:10]
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in text)[:40].strip("-")
    return f"{safe or 'source'}-{digest}"
