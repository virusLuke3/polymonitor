"""Environment-file loading at application and command startup boundaries."""

import os
from functools import lru_cache
from pathlib import Path


def environment_path(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[2]
    explicit = os.environ.get("POLYMONITOR_ENV_FILE") or os.environ.get("POLYDATA_AGENT_ENV_PATH")
    return Path(explicit).expanduser() if explicit else root / ".env"


@lru_cache(maxsize=4)
def _file_values(path: str) -> dict:
    from dotenv import dotenv_values
    return dict(dotenv_values(path)) if Path(path).is_file() else {}


def configured_value(name: str, default: str = "") -> str:
    """Process overrides the single private env file; never log either value."""
    if name in os.environ:
        return os.environ[name]
    if os.environ.get("POLYDATA_DISABLE_DOTENV", "").lower() in {"1", "true", "yes", "on"}:
        return default
    value = _file_values(str(environment_path())).get(name)
    return default if value is None else str(value)


def load_environment(project_root: Path | None = None) -> None:
    if os.environ.get("POLYDATA_DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    from dotenv import load_dotenv

    # Service EnvironmentFile/process values remain authoritative. There is no
    # implicit .env.local or scripts/.env source of private routing defaults.
    _file_values.cache_clear()
    load_dotenv(environment_path(project_root), override=False)
