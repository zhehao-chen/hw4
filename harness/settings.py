"""Load settings.yaml."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path

import yaml

from harness import ROOT


@dataclass(frozen=True)
class Settings:
    provider: str | None      # anthropic | openai-compatible; None until you choose
    model: str | None         # as your provider names it; None until you choose
    base_url: str | None      # openai-compatible only: your provider's endpoint
    api_key_env: str | None   # the environment variable that holds your key
    max_tokens: int
    effort: str | None
    fallbacks: str | None
    session_token_ceiling: int
    lab_token_ceiling: int
    jobs: int

    def digest(self) -> str:
        """A short hash of every setting, recorded on each run so you can prove what was held fixed."""
        text = repr(sorted(asdict(self).items()))
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_settings(path: Path | None = None) -> Settings:
    data = yaml.safe_load((path or ROOT / "settings.yaml").read_text())
    return Settings(
        provider=data.get("provider"),
        model=data.get("model"),
        base_url=data.get("base_url"),
        api_key_env=data.get("api_key_env"),
        max_tokens=int(data["max_tokens"]),
        effort=data.get("effort"),
        fallbacks=data.get("fallbacks"),
        session_token_ceiling=int(data["session_token_ceiling"]),
        lab_token_ceiling=int(data["lab_token_ceiling"]),
        jobs=int(data.get("jobs", 1)),
    )
