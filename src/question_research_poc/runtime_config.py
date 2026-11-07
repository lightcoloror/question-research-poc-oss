from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_CONFIG_PATH = _SOURCE_ROOT / "config" / "runtime.json"
_BUNDLED_CONFIG_PATH = Path(__file__).resolve().parent / "assets" / "runtime.json"
# A wheel must not rely on an untracked config beside its installation.
RUNTIME_CONFIG_PATH = _SOURCE_CONFIG_PATH if _SOURCE_CONFIG_PATH.is_file() else _BUNDLED_CONFIG_PATH
PROJECT_ROOT = _SOURCE_ROOT if _SOURCE_CONFIG_PATH.is_file() else Path.cwd()


def load_runtime_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else RUNTIME_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"runtime config not found: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"runtime config must be a JSON object: {config_path}")
    _validate_runtime_config(data, config_path)
    return data


def web_host(config: dict[str, Any] | None = None) -> str:
    cfg = config or load_runtime_config()
    return str(cfg["web"]["host"])


def web_port(config: dict[str, Any] | None = None) -> int:
    cfg = config or load_runtime_config()
    return int(cfg["web"]["port"])


def web_url(config: dict[str, Any] | None = None) -> str:
    cfg = config or load_runtime_config()
    return f"http://{web_host(cfg)}:{web_port(cfg)}"


def default_project_root(config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_runtime_config()
    configured = Path(str(cfg["project"]["default_root"])).expanduser()
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def _validate_runtime_config(data: dict[str, Any], config_path: Path) -> None:
    web = data.get("web")
    project = data.get("project")
    if not isinstance(web, dict):
        raise ValueError(f"runtime config missing web object: {config_path}")
    if not isinstance(project, dict):
        raise ValueError(f"runtime config missing project object: {config_path}")
    if not web.get("host"):
        raise ValueError(f"runtime config missing web.host: {config_path}")
    if web.get("port") is None:
        raise ValueError(f"runtime config missing web.port: {config_path}")
    int(web["port"])
    if not project.get("default_root"):
        raise ValueError(f"runtime config missing project.default_root: {config_path}")
