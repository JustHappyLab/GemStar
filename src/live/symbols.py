"""Stock symbol display-name helpers.

CALLING SPEC:
    names = symbol_names_from_file(path=Path) -> dict[str, str]
    names = symbol_names_from_dataframe(df=pd.DataFrame | None) -> dict[str, str]

SIDE EFFECTS:
    symbol_names_from_file reads a local JSON, CSV, or Parquet file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import pandas as pd


def symbol_names_from_dataframe(df: pd.DataFrame | None) -> dict[str, str]:
    """Extract ts_code -> Chinese name from a stock_basic-like DataFrame."""
    if df is None or df.empty or "ts_code" not in df.columns or "name" not in df.columns:
        return {}
    return _symbol_names_from_records(df[["ts_code", "name"]].to_dict("records"))


def symbol_names_from_file(path: str | Path) -> dict[str, str]:
    """Load ts_code -> name mapping from JSON, CSV, or Parquet."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        return _symbol_names_from_json(json.loads(p.read_text(encoding="utf-8")))
    if suffix == ".csv":
        return symbol_names_from_dataframe(pd.read_csv(p))
    if suffix == ".parquet":
        return symbol_names_from_dataframe(pd.read_parquet(p))
    raise ValueError(f"Unsupported stock_basic file type: {p.suffix}")


def _symbol_names_from_json(data: Any) -> dict[str, str]:
    if isinstance(data, dict):
        if all(isinstance(value, str) for value in data.values()):
            return _clean_mapping(data)
        if "items" in data and isinstance(data["items"], list):
            return _symbol_names_from_records(data["items"])
        return _symbol_names_from_records(data.values())
    if isinstance(data, list):
        return _symbol_names_from_records(data)
    return {}


def _symbol_names_from_records(records) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        code = _clean_value(row.get("ts_code") or row.get("symbol") or row.get("code"))
        name = _clean_value(row.get("name") or row.get("stock_name"))
        if code and name:
            names[code] = name
    return names


def _clean_mapping(mapping: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for code, name in mapping.items():
        clean_code = _clean_value(code)
        clean_name = _clean_value(name)
        if clean_code and clean_name:
            names[clean_code] = clean_name
    return names


def _clean_value(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
