from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator


def _parse_time_limit(value: str) -> int:
    """Parse a time limit string like '30m', '2h', '8h' into seconds."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([mh]?)", value.strip())
    if not match:
        raise ValueError(
            f"Invalid time_limit format: {value!r}. "
            "Expected a number optionally followed by 'm' (minutes) or 'h' (hours), "
            "e.g. '30m', '2h', '8h', or '3600' (raw seconds)."
        )
    amount_str, unit = match.groups()
    amount = float(amount_str)
    if unit == "h":
        return int(amount * 3600)
    elif unit == "m":
        return int(amount * 60)
    else:
        # bare number → treat as seconds
        return int(amount)


def _expand_env_vars(value: str) -> str:
    """Expand environment variable references like ${VAR_NAME} in a string."""
    def replacer(m: re.Match) -> str:
        var_name = m.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            return m.group(0)  # leave unexpanded if var not set
        return env_val

    return re.sub(r"\$\{([^}]+)\}", replacer, value)


class Config(BaseModel):
    model: str
    max_iterations: int = 50
    time_limit: str = "8h"
    api_key: Optional[str] = None

    # Derived field stored internally (seconds)
    _time_limit_seconds: int = 0

    @field_validator("api_key", mode="before")
    @classmethod
    def expand_api_key_env(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _expand_env_vars(str(v))

    @field_validator("model")
    @classmethod
    def validate_model_format(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError(
                f"model must be in 'provider/model-name' format, got: {v!r}"
            )
        return v

    @model_validator(mode="after")
    def compute_time_limit_seconds(self) -> "Config":
        self._time_limit_seconds = _parse_time_limit(self.time_limit)
        return self

    @property
    def provider(self) -> str:
        """Return the provider portion of the model string."""
        return self.model.split("/", 1)[0]

    @property
    def model_name(self) -> str:
        """Return the model name portion (after the first '/')."""
        return self.model.split("/", 1)[1]

    @property
    def time_limit_seconds(self) -> int:
        """Return the parsed time limit in seconds."""
        return _parse_time_limit(self.time_limit)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Load config from a YAML file.

        Args:
            path: Path to the YAML file. Defaults to 'autoresearch.yaml' in cwd.

        Returns:
            A Config instance populated from the file.

        Raises:
            FileNotFoundError: If the config file does not exist.
            ValueError: If required fields are missing or malformed.
        """
        if path is None:
            path = Path.cwd() / "autoresearch.yaml"
        else:
            path = Path(path)

        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Run 'autoresearch init' to create a template config, "
                "or create 'autoresearch.yaml' manually."
            )

        with path.open("r") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(
                f"Config file {path} must contain a YAML mapping at the top level."
            )

        return cls(**data)
