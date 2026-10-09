"""Settings, overridable through PITWALL_* environment variables."""

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Self


@dataclass(frozen=True)
class Settings:
    jolpica_url: str = "https://api.jolpi.ca/ergast/f1"
    openf1_url: str = "https://api.openf1.org/v1"
    cache_path: Path = Path(".cache/pitwall.sqlite3")
    timeout_s: float = 10.0
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> Self:
        """Defaults, overridden by PITWALL_<FIELD> variables (e.g. PITWALL_TIMEOUT_S=5)."""
        overrides = {}
        for field in fields(cls):
            name = f"PITWALL_{field.name.upper()}"
            raw = os.environ.get(name)
            if raw is None:
                continue
            try:
                overrides[field.name] = field.type(raw)
            except ValueError:
                raise ValueError(f"{name}={raw!r} is not a valid {field.type.__name__}") from None
        return cls(**overrides)
