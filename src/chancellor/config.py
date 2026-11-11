"""Application settings loaded from environment variables and an optional ``.env`` file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-5-5"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration.

    Attributes:
        save_dir: Folder where EU4 writes its ``.eu4`` save files.
        api_key: API key for the LLM provider. Only required from Phase 2 onwards.
        model: Model identifier used by the LLM client.
    """

    save_dir: Path | None
    api_key: str | None
    model: str = DEFAULT_MODEL


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` dotenv file, ignoring comments and blank lines."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(dotenv_path: Path | None = None) -> Settings:
    """Build :class:`Settings` from the process environment and a ``.env`` file.

    Real environment variables take precedence over values in the ``.env`` file.

    Args:
        dotenv_path: Path to the ``.env`` file. Defaults to ``./.env``.

    Returns:
        The resolved settings.
    """
    file_values = _read_dotenv(dotenv_path or Path(".env"))

    def get(key: str) -> str | None:
        return os.environ.get(key) or file_values.get(key) or None

    save_dir = get("EU4_SAVE_DIR")
    return Settings(
        save_dir=Path(save_dir).expanduser() if save_dir else None,
        api_key=get("ANTHROPIC_API_KEY"),
        model=get("CHANCELLOR_MODEL") or DEFAULT_MODEL,
    )
