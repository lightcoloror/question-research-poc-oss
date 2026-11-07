from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .models import dataclass_to_dict, new_id, now_iso
from .orchestrator import add_source
from .storage import read_json, write_json


SOURCE_INBOX_SCHEMA = "question_research_source_inbox.v1"
VALID_STATUSES = {"candidate", "imported", "rejected"}


def add_inbox_item(
    root: str | Path,
    *,
    kind: str,
    title: str,
    location: str = "",
    url: str = "",
    path: str = "",
    source_tool: str = "",
    quality_hint: str = "unknown",
    notes: str = "",
) -> dict[str, Any]:
    project_root = Path(root)
    items = _read_items(project_root)
    item = {
        "id": new_id("inbox"),
        "kind": kind,
        "title": title,
        "location": location or url or path,
        "url": url,
        "path": path,
        "source_tool": source_tool,
        "quality_hint": quality_hint,
        "notes": notes,
        "import_status": "candidate",
        "review_note": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    items.append(item)
    _write_items(project_root, items)
    return item


def list_inbox_items(root: str | Path, status: str | None = None) -> list[dict[str, Any]]:
    items = _read_items(Path(root))
    return [item for item in items if item.get("import_status") == status] if status else items


def get_source_inbox(root: str | Path, status: str | None = None) -> dict[str, Any]:
    project_root = Path(root)
    items = list_inbox_items(project_root, status=status)
    return {
        "ok": True,
        "schema": SOURCE_INBOX_SCHEMA,
        "root": str(project_root),
        "path": str(_inbox_path(project_root)),
        "items": items,
        "counts": _counts(items),
        "human_review_required": any(item.get("import_status") == "candidate" for item in items),
    }


def import_inbox_item_as_source(root: str | Path, item_id: str, *, source_quality: str = "unknown") -> dict[str, Any]:
    project_root = Path(root)
    items = _read_items(project_root)
    item = _find_item(items, item_id)
    if item.get("import_status") == "rejected":
        raise ValueError("rejected inbox item cannot be imported")
    source = add_source(
        project_root,
        title=str(item.get("title") or "Inbox source"),
        url=str(item.get("url") or ""),
        path=str(item.get("path") or item.get("location") or ""),
        source_type=str(item.get("kind") or "inbox"),
        quality=source_quality,
        notes=_source_notes(item),
    )
    item["import_status"] = "imported"
    item["source_id"] = source.id
    item["updated_at"] = now_iso()
    _write_items(project_root, items)
    return {
        "ok": True,
        "schema": SOURCE_INBOX_SCHEMA,
        "item": item,
        "source": dataclass_to_dict(source),
        "human_review_required": True,
        "boundary": "Inbox import creates a candidate source only. Source quality still requires human review.",
    }


def reject_inbox_item(root: str | Path, item_id: str, *, note: str = "") -> dict[str, Any]:
    project_root = Path(root)
    items = _read_items(project_root)
    item = _find_item(items, item_id)
    item["import_status"] = "rejected"
    item["review_note"] = note
    item["updated_at"] = now_iso()
    _write_items(project_root, items)
    return item


def _source_notes(item: dict[str, Any]) -> str:
    lines = [
        "Imported from source inbox.",
        f"inbox_id: {item.get('id', '')}",
        f"source_tool: {item.get('source_tool', '')}",
        f"quality_hint: {item.get('quality_hint', 'unknown')}",
        "Status: candidate source; requires human source-quality review.",
    ]
    if item.get("notes"):
        lines.append(f"notes: {item.get('notes')}")
    return "\n".join(lines)


def _find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise ValueError(f"source inbox item not found: {item_id}")


def _inbox_path(root: Path) -> Path:
    return root / "state" / "source-inbox.json"


def _read_items(root: Path) -> list[dict[str, Any]]:
    path = _inbox_path(root)
    if not path.exists():
        return []
    data = read_json(path)
    if isinstance(data, dict):
        items = data.get("items", [])
        return items if isinstance(items, list) else []
    return data if isinstance(data, list) else []


def _write_items(root: Path, items: list[dict[str, Any]]) -> None:
    write_json(_inbox_path(root), {"schema": SOURCE_INBOX_SCHEMA, "items": items})


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(item.get("import_status", "candidate")) for item in items)
    return {
        "total": len(items),
        "candidate": counter.get("candidate", 0),
        "imported": counter.get("imported", 0),
        "rejected": counter.get("rejected", 0),
    }
