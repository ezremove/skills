"""Configuration helpers for the EzRemove remove-background skill."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_API_BASE = "https://api.ezremove.ai"


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read a minimal .env file without adding a runtime dependency."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _shared_config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base_dir = Path(config_home) if config_home else Path.home() / ".config"
    return base_dir / "ezremove" / ".env"


def get_api_key() -> Optional[str]:
    """Return the API key from the environment or shared EzRemove config."""
    value = os.environ.get("EZ_REMOVE_API_KEY", "").strip()
    if value:
        return value
    env_values = _read_dotenv(_shared_config_path())
    return env_values.get("EZ_REMOVE_API_KEY", "").strip() or None


def get_api_base() -> str:
    """Return the production API base unless explicitly overridden."""
    return os.environ.get("EZREMOVE_API_BASE", DEFAULT_API_BASE).rstrip("/")
