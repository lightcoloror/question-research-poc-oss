from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from .models import ResearchProject, dataclass_to_dict, project_paths


def ensure_project_dirs(root: str | Path) -> dict[str, Path]:
    paths = project_paths(root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["notes"].mkdir(parents=True, exist_ok=True)
    return paths


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with _file_lock(path):
        try:
            tmp_path.write_bytes(text.encode("utf-8"))
            os.replace(tmp_path, path)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def rewrite_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path):
        _write_jsonl_unlocked(path, list(rows))


def mutate_jsonl(path: Path, mutator: Callable[[list[dict[str, Any]]], Any]) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path):
        rows = _read_jsonl_unlocked(path)
        result = mutator(rows)
        _write_jsonl_unlocked(path, rows)
        return result


def load_project(root: str | Path) -> ResearchProject:
    paths = project_paths(root)
    data = read_json(paths["project"])
    return ResearchProject(**data)


def save_project(root: str | Path, project: ResearchProject) -> None:
    paths = ensure_project_dirs(root)
    write_json(paths["project"], dataclass_to_dict(project))


@contextmanager
def _file_lock(path: Path, *, timeout_seconds: float = 10.0, poll_seconds: float = 0.05):
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        except (FileExistsError, PermissionError) as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for file lock: {lock_path}") from exc
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _read_jsonl_unlocked(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_jsonl_unlocked(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
