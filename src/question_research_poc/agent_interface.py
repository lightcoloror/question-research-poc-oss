from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dashboard import build_project_dashboard
from .local_tool_health import build_local_tool_health_dashboard
from .orchestrator import list_records
from .project_overview import build_project_overview
from .research_plan import build_research_plan
from .review_state import build_review_queue, build_workflow_payload
from .storage import load_project
from .workflow_engine import audit_research_gates, route_research_task, run_multi_perspective_review, run_reader_persona_review


def get_project_status(root: str | Path) -> dict[str, Any]:
    payload = _agent_payload(root)
    workflow = payload.get("workflow", {})
    gate_audit = workflow.get("gate_audit", {}) if isinstance(workflow, dict) else {}
    blockers = gate_audit.get("blockers", []) if isinstance(gate_audit, dict) else []
    return {
        "ok": bool(payload.get("ok")),
        "root": payload.get("root"),
        "question": (payload.get("project") or {}).get("question") if isinstance(payload.get("project"), dict) else "",
        "counts": {
            "sources": len(payload.get("sources", [])),
            "claims": len(payload.get("claims", [])),
            "evidence": len(payload.get("evidence", [])),
            "reviews": len(payload.get("reviews", [])),
            "review_queue": len(payload.get("review_queue", [])),
            "workflow_artifacts": len(workflow.get("artifacts", [])) if isinstance(workflow, dict) else 0,
        },
        "stage": payload.get("dashboard", {}).get("stage_detail", {}) if isinstance(payload.get("dashboard"), dict) else {},
        "workflow": {
            "has_route": bool(workflow.get("has_route")) if isinstance(workflow, dict) else False,
            "has_gate_audit": bool(workflow.get("has_gate_audit")) if isinstance(workflow, dict) else False,
            "has_next_steps": bool(workflow.get("has_next_steps")) if isinstance(workflow, dict) else False,
            "can_proceed": bool(gate_audit.get("can_proceed", gate_audit.get("ok", False))) if isinstance(gate_audit, dict) else False,
            "next_gate": gate_audit.get("next_gate", "") if isinstance(gate_audit, dict) else "",
            "blocker_count": len(blockers) if isinstance(blockers, list) else 0,
        },
    }


def get_gate_details(root: str | Path, gate_id: str | None = None) -> dict[str, Any]:
    workflow = build_workflow_payload(root)
    details = workflow.get("gate_details", {}) if isinstance(workflow, dict) else {}
    if gate_id:
        return {"gate_id": gate_id, "detail": details.get(gate_id, {"record_count": 0, "records": []})}
    return {"gate_details": details}


def get_review_queue(root: str | Path, item_type: str | None = None) -> dict[str, Any]:
    queue = build_review_queue(root)
    if item_type:
        queue = [item for item in queue if item.get("item_type") == item_type]
    return {"count": len(queue), "items": queue}


def get_project_dashboard(root: str | Path) -> dict[str, Any]:
    workflow = build_workflow_payload(root)
    review_queue = build_review_queue(root)
    return build_project_dashboard(root, workflow=workflow, review_queue=review_queue)


def get_project_overview(root: str | Path) -> dict[str, Any]:
    return build_project_overview(root)


def get_tool_health_dashboard() -> dict[str, Any]:
    return build_local_tool_health_dashboard()


def read_workflow_artifact(root: str | Path, artifact_id: str, format: str = "markdown") -> dict[str, Any]:
    workflow = build_workflow_payload(root)
    artifacts = workflow.get("artifacts", []) if isinstance(workflow, dict) else []
    artifact = next((item for item in artifacts if item.get("id") == artifact_id), None)
    if not artifact:
        raise ValueError(f"unknown workflow artifact: {artifact_id}")
    path_key = "json_path" if format == "json" else "markdown_path"
    path = Path(str(artifact.get(path_key) or ""))
    if not path.exists():
        raise FileNotFoundError(f"workflow artifact not found: {path}")
    if format == "json":
        content: Any = json.loads(path.read_text(encoding="utf-8"))
    else:
        content = path.read_text(encoding="utf-8")
    return {"artifact": artifact, "format": format, "path": str(path), "content": content}


def run_next_step(root: str | Path, gate_id: str, *, write: bool = True) -> dict[str, Any]:
    payload = _agent_payload(root)
    next_steps = _next_steps(payload)
    step = next((item for item in next_steps if item.get("gate_id") == gate_id), None)
    if not step:
        return {"ok": False, "status": "not_found", "gate_id": gate_id, "message": "No pending next step for this gate."}
    if step.get("requires_human_confirmation") or not step.get("can_agent_execute"):
        return {"ok": True, "status": "human_required", "gate_id": gate_id, "step": step}
    if gate_id == "task_route_present":
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        result = route_research_task(root, question=project.get("question"), write=write)
    elif gate_id in {"research_plan_present", "counter_evidence_checked"}:
        result = build_research_plan(root, write=write, add_claims=True)
    elif gate_id == "multi_perspective_review_present":
        result = run_multi_perspective_review(root, write=write)
    elif gate_id == "reader_persona_review_present":
        result = run_reader_persona_review(root, write=write)
    elif gate_id == "result_file_chain_complete":
        result = audit_research_gates(root, target_stage="final_answer", write=write)
    else:
        return {"ok": True, "status": "requires_input", "gate_id": gate_id, "step": step}
    return {"ok": True, "status": "executed", "gate_id": gate_id, "step": step, "result": result, "state": get_project_status(root)}


def _next_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    workflow = payload.get("workflow", {})
    audit = workflow.get("gate_audit", {}) if isinstance(workflow, dict) else {}
    next_steps_payload = workflow.get("next_steps", {}) if isinstance(workflow, dict) else {}
    steps = audit.get("next_steps") if isinstance(audit, dict) else None
    if not steps and isinstance(next_steps_payload, dict):
        steps = next_steps_payload.get("next_steps")
    return steps if isinstance(steps, list) else []


def _agent_payload(root: str | Path) -> dict[str, Any]:
    project_root = Path(root)
    workflow = build_workflow_payload(project_root)
    review_queue = build_review_queue(project_root)
    if not (project_root / "research.json").exists():
        return {
            "ok": False,
            "root": str(project_root),
            "project": None,
            "sources": [],
            "claims": [],
            "evidence": [],
            "reviews": [],
            "workflow": workflow,
            "review_queue": review_queue,
            "dashboard": build_project_dashboard(project_root, workflow=workflow, review_queue=review_queue),
        }
    return {
        "ok": True,
        "root": str(project_root),
        "project": _jsonable(load_project(project_root)),
        "sources": list_records(project_root, "sources"),
        "claims": list_records(project_root, "claims"),
        "evidence": list_records(project_root, "evidence"),
        "reviews": list_records(project_root, "reviews"),
        "workflow": workflow,
        "review_queue": review_queue,
        "dashboard": build_project_dashboard(project_root, workflow=workflow, review_queue=review_queue),
    }


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return value.__dict__
    if isinstance(value, Path):
        return str(value)
    return value
