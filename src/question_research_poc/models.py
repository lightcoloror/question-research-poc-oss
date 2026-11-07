from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class ResearchProject:
    id: str
    question: str
    created_at: str
    status: str = "open"
    notes: str = ""


@dataclass
class SourceRecord:
    id: str
    source_type: str
    title: str
    url: str = ""
    path: str = ""
    quality: str = "unknown"
    notes: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class SourceReview:
    id: str
    source_id: str
    quality: str
    reason: str = ""
    reviewer: str = "human"
    created_at: str = field(default_factory=now_iso)


@dataclass
class ClaimRecord:
    id: str
    text: str
    status: str = "open"
    notes: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class EvidenceRecord:
    id: str
    claim_id: str
    source_id: str
    quote_or_note: str
    relation: str = "unknown"
    status: str = "candidate"
    confidence: str = "unknown"
    notes: str = ""
    created_at: str = field(default_factory=now_iso)


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)


def project_paths(root: str | Path) -> dict[str, Path]:
    base = Path(root)
    return {
        "root": base,
        "project": base / "research.json",
        "sources": base / "sources.jsonl",
        "source_reviews": base / "source-reviews.jsonl",
        "claims": base / "claims.jsonl",
        "evidence": base / "evidence.jsonl",
        "notes": base / "notes",
        "graph": base / "graph-candidates.jsonl",
        "reviews": base / "reviews.jsonl",
    }
