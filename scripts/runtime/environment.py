"""Environment-file loading at application and command startup boundaries."""

import os
from pathlib import Path


def load_environment(project_root: Path | None = None) -> None:
    if os.environ.get("POLYDATA_DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    from dotenv import load_dotenv

    root = project_root or Path(__file__).resolve().parents[2]
    # Preserve deployed precedence: process > .env > .env.local > scripts/.env.
    paths = [root / ".env", root / ".env.local", root / "scripts" / ".env"]
    explicit = os.environ.get("POLYDATA_AGENT_ENV_PATH")
    if explicit:
        paths.insert(0, Path(explicit).expanduser())
    for path in paths:
        load_dotenv(path, override=False)
