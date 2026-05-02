"""Factor pool reader and writer using FactorPoolV1 schema.

CALLING SPEC:
    pool = load_pool() -> FactorPoolV1
        Reads factors/pool.json and returns a validated FactorPoolV1.

    save_pool(pool: FactorPoolV1) -> None
        Writes the pool back to factors/pool.json.

    pool_path() -> Path
        Returns the absolute path to factors/pool.json.

SIDE EFFECTS:
    save_pool() writes to factors/pool.json.
"""

import json
from pathlib import Path

from src.schemas.factor import FactorPoolV1

_POOL_PATH = Path(__file__).resolve().parent.parent.parent / "factors" / "pool.json"


def pool_path() -> Path:
    """Return absolute path to factors/pool.json."""
    return _POOL_PATH


def load_pool(path: Path | None = None) -> FactorPoolV1:
    """Load and validate factor pool from JSON file."""
    return FactorPoolV1.load(path or _POOL_PATH)


def save_pool(pool: FactorPoolV1, path: Path | None = None) -> None:
    """Write factor pool to JSON file."""
    target = path or _POOL_PATH
    target.write_text(json.dumps(pool.model_dump(), indent=2, ensure_ascii=False) + "\n")
