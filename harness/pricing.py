"""Price model calls from pricing.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from harness import ROOT


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    source: str | None = None   # where this line's prices come from
    read: str | None = None     # the date you read them


def _price(row: dict) -> Price:
    """A price line. Only input and output are required: a vendor without cache
    pricing is charged its input price for cache reads and writes."""
    return Price(input=row["input"], output=row["output"],
                 cache_write_5m=row.get("cache_write_5m", row["input"]),
                 cache_write_1h=row.get("cache_write_1h", row["input"]),
                 cache_read=row.get("cache_read", row["input"]),
                 source=row.get("source"), read=str(row["read"]) if row.get("read") else None)


class PriceSheet:
    def __init__(self, path: Path | None = None):
        data = yaml.safe_load((path or ROOT / "pricing.yaml").read_text())
        self.read_date = str(data["read_date"])
        self.source = data["source"]
        self.models = {name: _price(row) for name, row in data["models"].items()}

    def find(self, model: str) -> Price | None:
        """The line for a model: its exact name, or else the longest name it starts
        with, because many APIs report a dated name (gpt-x-2026-01-01 for gpt-x)."""
        if model in self.models:
            return self.models[model]
        prefixes = [name for name in self.models if model.startswith(name)]
        return self.models[max(prefixes, key=len)] if prefixes else None

    def cost(self, model: str, usage) -> float | None:
        """USD for one call, or None when the model is not on the sheet.

        Cache writes are priced at the 5-minute rate unless the usage says they
        were 1-hour writes. Every token class is priced at its own line.
        """
        price = self.find(model)
        if price is None:
            return None
        write_1h = getattr(usage, "cache_creation_1h_tokens", 0) or 0
        write_5m = (usage.cache_creation_input_tokens or 0) - write_1h
        total = (
            usage.input_tokens * price.input
            + usage.output_tokens * price.output
            + (usage.cache_read_input_tokens or 0) * price.cache_read
            + write_5m * price.cache_write_5m
            + write_1h * price.cache_write_1h
        )
        return total / 1_000_000
