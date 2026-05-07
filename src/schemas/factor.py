"""Factor registry and health report schemas.

CALLING SPEC:
    FactorPoolV1.load(path) reads factors/pool.json.
    FactorRegistryEntryV1 models a single factor in any lifecycle state.
    FactorHealthReportV1 captures monitor output per factor per run.

SIDE EFFECTS:
    None.
"""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class FactorRegistryEntryV1(BaseModel):
    name: str
    source: str = ""
    computation: str = ""
    expression: str = ""
    hypothesis: str = ""
    ic_mean: float | None = None
    ic_ir: float | None = None
    ic_positive_rate: float | None = None
    coverage: float | None = None
    direction: Literal["positive", "negative", "neutral"] = "positive"
    horizon: str = "1d"
    universe: str = "a_share_core"
    last_updated: str = ""
    discovered_in_run: str = ""
    status: Literal[
        "candidate",
        "implemented",
        "tested",
        "active",
        "watchlist",
        "retired",
    ] = "candidate"


class FactorPoolV1(BaseModel):
    version: int = 2
    last_updated: str = ""
    active: list[FactorRegistryEntryV1] = Field(default_factory=list)
    watchlist: list[FactorRegistryEntryV1] = Field(default_factory=list)
    retired: list[FactorRegistryEntryV1] = Field(default_factory=list)
    candidates: list[FactorRegistryEntryV1] = Field(default_factory=list)

    def all_entries(self) -> list[FactorRegistryEntryV1]:
        return self.active + self.watchlist + self.retired + self.candidates

    def get(self, name: str) -> FactorRegistryEntryV1 | None:
        for entry in self.all_entries():
            if entry.name == name:
                return entry
        return None

    def is_registered(self, name: str) -> bool:
        return self.get(name) is not None

    def is_active_or_candidate(self, name: str) -> bool:
        entry = self.get(name)
        return entry is not None and entry.status in ("active", "candidate")

    @classmethod
    def load(cls, path: str | Path) -> "FactorPoolV1":
        data = Path(path).read_text()
        import json
        return cls.model_validate(json.loads(data))


class FactorHealthEntry(BaseModel):
    factor_name: str
    ic_mean: float | None = None
    ic_ir: float | None = None
    ic_positive_rate: float | None = None
    coverage: float | None = None
    status: Literal["healthy", "degraded", "critical"] = "healthy"
    note: str = ""


class FactorHealthReportV1(BaseModel):
    version: Literal["FactorHealthReportV1"] = "FactorHealthReportV1"
    run_id: str
    as_of_date: date
    entries: list[FactorHealthEntry] = Field(default_factory=list)
    watchlist_triggers: list[str] = Field(default_factory=list)
