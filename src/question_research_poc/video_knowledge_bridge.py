from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .bridge_runs import create_bridge_run
from .runtime_paths import video_knowledge_root


DEFAULT_VIDEO_KNOWLEDGE_ROOT = video_knowledge_root()


def plan_video_knowledge_run(
    media_path: str | Path,
    workspace: str | Path,
    *,
    title: str = "",
    max_frames: int = 80,
    build_initial_bundle: bool = True,
    root: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    tool_root = _resolve_tool_root(root)
    wrapper = tool_root / "scripts" / "video-knowledge.ps1"
    media = Path(media_path).expanduser()
    run_workspace = Path(workspace).expanduser()
    command = [
        str(wrapper),
        "prepare-local-video-run",
        str(media),
        str(run_workspace),
    ]
    if title:
        command.extend(["--title", title])
    if build_initial_bundle:
        command.append("--build-initial-bundle")
    command.extend(["--max-frames", str(int(max_frames))])
    bundle_dir = run_workspace / "webui-bundle"
    exports_dir = run_workspace / "exports"
    result = {
        "schema": "question_research_video_knowledge_plan.v1",
        "ok": True,
        "read_only": True,
        "tool": "video-knowledge-pipeline",
        "tool_root": str(tool_root),
        "wrapper": str(wrapper),
        "wrapper_exists": wrapper.exists(),
        "media_path": str(media),
        "media_exists": media.exists(),
        "workspace": str(run_workspace),
        "title": title,
        "max_frames": int(max_frames),
        "build_initial_bundle": bool(build_initial_bundle),
        "command": command,
        "expected_artifacts": {
            "review_bundle": str(bundle_dir),
            "review_html": str(bundle_dir / "review.html").replace("\\", "/"),
            "knowledge_note": str(exports_dir / "knowledge-note.md").replace("\\", "/"),
            "full_transcript": str(exports_dir / "full-transcript.md").replace("\\", "/"),
        },
        "delegation_boundary": "question-research-poc only plans and records the video run. ASR, frame routing, OCR/document parsing, multimodal frame analysis, temporal analysis, review bundle generation, and knowledge-note export stay in video-knowledge-pipeline.",
        "operator_next_steps": [
            "确认本地视频路径存在。",
            "执行 command 中的 prepare-local-video-run。",
            "在 review_html 中人工审核视频知识提取结果。",
            "后续通过导入视频知识包把 knowledge-note/full-transcript 作为候选来源和证据接入本研究项目。",
        ],
        "failure_next_action": "If this plan cannot run, check the media path, video-knowledge-pipeline wrapper path, local ASR configuration, and multimodal API/local VLM configuration.",
    }
    if project_root:
        result["bridge_run"] = create_bridge_run(
            project_root,
            tool="video-knowledge-pipeline",
            action="plan_video_knowledge_run",
            request={"media_path": str(media), "workspace": str(run_workspace), "title": title, "max_frames": int(max_frames)},
            command=command,
            status="planned",
            artifact_paths=list(result["expected_artifacts"].values()),
            recovery_hint=result["failure_next_action"],
            response={"plan": {key: value for key, value in result.items() if key != "bridge_run"}},
        )
    return result


def run_video_knowledge_tool(
    args: list[str],
    *,
    root: str | Path | None = None,
    timeout_seconds: int = 0,
) -> dict[str, Any]:
    tool_root = _resolve_tool_root(root)
    wrapper = tool_root / "scripts" / "video-knowledge.ps1"
    if not wrapper.exists():
        raise FileNotFoundError(f"video-knowledge-pipeline wrapper not found: {wrapper}")
    clean_args = [str(arg) for arg in args if str(arg)]
    command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(wrapper), *clean_args]
    completed = subprocess.run(
        command,
        cwd=str(tool_root),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=int(timeout_seconds or 0) or None,
        check=False,
    )
    return {
        "schema": "question_research_video_knowledge_bridge.v1",
        "tool_root": str(tool_root),
        "wrapper": str(wrapper),
        "args": clean_args,
        "command": command,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": _parse_json(completed.stdout),
    }


def check_video_run_artifacts(bundle_dir: str | Path) -> dict[str, Any]:
    bundle = Path(bundle_dir).expanduser()
    exports_dir = bundle / "exports" if (bundle / "exports").exists() else bundle.parent / "exports"
    expected = {
        "review_bundle": bundle,
        "review_html": bundle / "review.html",
        "knowledge_note": exports_dir / "knowledge-note.md",
        "full_transcript": exports_dir / "full-transcript.md",
    }
    artifacts = {
        key: {"path": str(path).replace("\\", "/"), "exists": path.exists(), "size": path.stat().st_size if path.exists() and path.is_file() else 0}
        for key, path in expected.items()
    }
    missing = [key for key, row in artifacts.items() if not row["exists"]]
    return {
        "schema": "question_research_video_artifact_status.v1",
        "ok": not missing,
        "bundle_dir": str(bundle),
        "artifacts": artifacts,
        "missing": missing,
        "next_actions": [] if not missing else [
            "先运行 video-knowledge-pipeline 的 prepare-local-video-run。",
            "确认 review.html、exports/knowledge-note.md、exports/full-transcript.md 已生成后再导入。",
        ],
    }


def _resolve_tool_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("VIDEO_KNOWLEDGE_PIPELINE_ROOT") or DEFAULT_VIDEO_KNOWLEDGE_ROOT).expanduser().resolve()


def _parse_json(stdout: str) -> Any:
    text = str(stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
