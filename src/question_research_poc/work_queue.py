from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .agent_runbook import build_agent_runbook
from .models import new_id, now_iso
from .storage import read_json, write_json
from .tool_executor import run_local_tool_action


WORK_QUEUE_SCHEMA = "question_research_work_queue.v1"
VALID_STATUSES = {"pending", "running", "done", "failed", "needs_human"}


def enqueue_task(
    root: str | Path,
    *,
    kind: str,
    title: str,
    command: str = "",
    status: str = "pending",
    human_boundary: str = "",
    artifact_paths: list[str] | None = None,
    tool_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid queue status: {status}")
    project_root = Path(root)
    tasks = _read_tasks(project_root)
    now = now_iso()
    task = {
        "id": new_id("task"),
        "kind": kind,
        "title": title,
        "command": command,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "human_boundary": human_boundary,
        "artifact_paths": artifact_paths or [],
    }
    if tool_action:
        task["tool_action"] = _normalize_tool_action(tool_action)
    tasks.append(task)
    _write_tasks(project_root, tasks)
    return task


def list_tasks(root: str | Path, status: str | None = None) -> list[dict[str, Any]]:
    tasks = _read_tasks(Path(root))
    return [task for task in tasks if task.get("status") == status] if status else tasks


def get_work_queue(root: str | Path, status: str | None = None) -> dict[str, Any]:
    project_root = Path(root)
    tasks = list_tasks(project_root, status=status)
    return {
        "ok": True,
        "schema": WORK_QUEUE_SCHEMA,
        "root": str(project_root),
        "path": str(_queue_path(project_root)),
        "tasks": tasks,
        "counts": _counts(tasks),
        "human_review_required": any(task.get("status") == "needs_human" for task in tasks),
    }


def update_task_status(root: str | Path, task_id: str, status: str, note: str = "") -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid queue status: {status}")
    project_root = Path(root)
    tasks = _read_tasks(project_root)
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = status
            task["updated_at"] = now_iso()
            if note:
                task["note"] = note
            _write_tasks(project_root, tasks)
            return task
    raise ValueError(f"work queue item not found: {task_id}")


def run_work_queue_item(root: str | Path, task_id: str, *, execute: bool = False, timeout_seconds: int = 60) -> dict[str, Any]:
    project_root = Path(root)
    tasks = _read_tasks(project_root)
    for task in tasks:
        if task.get("id") != task_id:
            continue
        tool_action = task.get("tool_action")
        if not isinstance(tool_action, dict):
            return {
                "ok": False,
                "schema": WORK_QUEUE_SCHEMA,
                "root": str(project_root),
                "task": task,
                "executed": False,
                "dry_run": not execute,
                "error": "work queue item has no explicit tool_action; preview command for manual execution only",
                "human_review_required": bool(task.get("status") == "needs_human" or task.get("human_boundary")),
            }
        if task.get("status") == "needs_human":
            return {
                "ok": False,
                "schema": WORK_QUEUE_SCHEMA,
                "root": str(project_root),
                "task": task,
                "executed": False,
                "dry_run": not execute,
                "error": "work queue item requires human review and cannot be executed by agent",
                "human_review_required": True,
            }
        if execute:
            task["status"] = "running"
            task["updated_at"] = now_iso()
            _write_tasks(project_root, tasks)
        if tool_action.get("kind") == "bridge_action":
            from .bridge_actions import run_bridge_action

            result = run_bridge_action(
                project_root,
                str(tool_action.get("action", "")),
                args=tool_action.get("args") if isinstance(tool_action.get("args"), dict) else {},
                execute=execute,
                timeout_seconds=timeout_seconds,
            )
        elif tool_action.get("kind") == "research_loop":
            result = _run_research_loop_action(project_root, tool_action, execute=execute, timeout_seconds=timeout_seconds)
        else:
            result = run_local_tool_action(
                str(tool_action.get("tool_id", "")),
                str(tool_action.get("action", "")),
                args=tool_action.get("args") if isinstance(tool_action.get("args"), dict) else {},
                execute=execute,
                timeout_seconds=timeout_seconds,
                project_root=project_root,
                task_id=task_id,
            )
        if execute:
            task["status"] = _task_status_from_result(result)
            task["updated_at"] = now_iso()
            if result.get("bridge_run_id"):
                task["bridge_run_id"] = str(result["bridge_run_id"])
            if result.get("bridge_run_path"):
                task["bridge_run_path"] = str(result["bridge_run_path"])
            if result.get("result_path"):
                task.setdefault("artifact_paths", []).append(str(result["result_path"]))
            for path in result.get("artifact_paths", []) if isinstance(result.get("artifact_paths"), list) else []:
                if path and str(path) not in task.setdefault("artifact_paths", []):
                    task["artifact_paths"].append(str(path))
            if result.get("imported_counts"):
                task["imported_counts"] = result["imported_counts"]
            if result.get("blocked_by_backend"):
                task["blocked_by_backend"] = str(result["blocked_by_backend"])
            if result.get("run_dir"):
                task["last_run_dir"] = str(result["run_dir"])
            if result.get("error") or result.get("suggested_recovery") or result.get("recovery_hint"):
                task["note"] = str(result.get("error") or result.get("suggested_recovery") or result.get("recovery_hint"))
            _write_tasks(project_root, tasks)
        return {
            "ok": bool(result.get("ok")),
            "schema": WORK_QUEUE_SCHEMA,
            "root": str(project_root),
            "task": task,
            "tool_result": result,
            "executed": bool(result.get("executed")),
            "dry_run": not execute,
            "queue": get_work_queue(project_root),
        }
    raise ValueError(f"work queue item not found: {task_id}")


def enqueue_runbook_tasks(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    runbook = build_agent_runbook(project_root)
    added: list[dict[str, Any]] = []
    existing_commands = {str(task.get("command", "")) for task in _read_tasks(project_root) if task.get("command")}
    for command in runbook.get("commands", []):
        command_text = str(command.get("command", ""))
        if not command_text or command_text in existing_commands:
            continue
        added.append(
            enqueue_task(
                project_root,
                kind="agent_command",
                title=str(command.get("title") or "Agent command"),
                command=command_text,
                status="pending",
                human_boundary=str(command.get("boundary") or ""),
                tool_action=command.get("tool_action") if isinstance(command.get("tool_action"), dict) else None,
            )
        )
        existing_commands.add(command_text)
    for item in runbook.get("human_tasks", []):
        added.append(
            enqueue_task(
                project_root,
                kind=str(item.get("item_type") or "human_review"),
                title=str(item.get("title") or "Human review"),
                status="needs_human",
                human_boundary=str(item.get("action") or "Requires human review."),
            )
        )
    queue = get_work_queue(project_root)
    return {**queue, "added": added, "added_count": len(added)}


def _queue_path(root: Path) -> Path:
    return root / "state" / "work-queue.json"


def _read_tasks(root: Path) -> list[dict[str, Any]]:
    path = _queue_path(root)
    if not path.exists():
        return []
    data = read_json(path)
    if isinstance(data, dict):
        tasks = data.get("tasks", [])
        return tasks if isinstance(tasks, list) else []
    return data if isinstance(data, list) else []


def _write_tasks(root: Path, tasks: list[dict[str, Any]]) -> None:
    write_json(_queue_path(root), {"schema": WORK_QUEUE_SCHEMA, "tasks": tasks})


def _counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(task.get("status", "pending")) for task in tasks)
    return {
        "total": len(tasks),
        "pending": counter.get("pending", 0),
        "running": counter.get("running", 0),
        "done": counter.get("done", 0),
        "failed": counter.get("failed", 0),
        "needs_human": counter.get("needs_human", 0),
    }


def _normalize_tool_action(tool_action: dict[str, Any]) -> dict[str, Any]:
    if str(tool_action.get("kind") or "") == "bridge_action":
        action = str(tool_action.get("action") or "")
        if not action:
            raise ValueError("bridge_action tool_action requires action")
        args = tool_action.get("args") if isinstance(tool_action.get("args"), dict) else {}
        return {"kind": "bridge_action", "action": action, "args": args}
    if str(tool_action.get("kind") or "") == "research_loop":
        args = tool_action.get("args") if isinstance(tool_action.get("args"), dict) else {}
        return {"kind": "research_loop", "args": args}
    tool_id = str(tool_action.get("tool_id") or "")
    action = str(tool_action.get("action") or "")
    if not tool_id or not action:
        raise ValueError("tool_action requires tool_id and action")
    args = tool_action.get("args") if isinstance(tool_action.get("args"), dict) else {}
    return {"tool_id": tool_id, "action": action, "args": args}


def _task_status_from_result(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    if status == "needs_human":
        return "needs_human"
    if status == "blocked_bridge_down":
        return "needs_human"
    if result.get("ok"):
        return "done"
    return "failed"


def _run_research_loop_action(project_root: Path, tool_action: dict[str, Any], *, execute: bool, timeout_seconds: int) -> dict[str, Any]:
    args = tool_action.get("args") if isinstance(tool_action.get("args"), dict) else {}
    if not execute:
        return {
            "ok": True,
            "schema": "question_research_loop_action.v1",
            "root": str(project_root),
            "action": "research_loop",
            "status": "planned",
            "executed": False,
            "dry_run": True,
            "args": args,
            "candidate_only": True,
            "verified_evidence_created": False,
            "human_review_required": True,
            "review_gate_required": True,
        }
    from .research_loop import run_research_loop

    result = run_research_loop(
        project_root,
        query=str(args.get("query") or "") or None,
        mode=str(args.get("mode") or "academic"),
        rounds=int(args.get("rounds") or 3),
        max_results=int(args.get("max_results") or 8),
        max_queries_per_round=int(args.get("max_queries_per_round") or 3),
        no_network=bool(args.get("no_network", False)),
        fetch=bool(args.get("fetch", True)),
        base_url=str(args.get("base_url") or "") or None,
        timeout_seconds=int(args.get("timeout_seconds") or timeout_seconds),
        status_timeout_seconds=int(args.get("status_timeout_seconds") or 5),
    )
    return {
        **result,
        "schema": "question_research_loop_action.v1",
        "action": "research_loop",
        "executed": True,
        "dry_run": False,
    }
