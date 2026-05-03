"""Unified output formatting — table (human) or JSON (machine)."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()

OutputFormat = str  # "table" | "json"


def emit(data: Any, *, format: OutputFormat = "table", title: str = "") -> None:
    """Emit *data* in the requested format.

    For ``format="table"``:
      - dict  → single-row key/value table
      - list[dict] → multi-row table
      - str   → plain print

    For ``format="json"``:
      - Always ``json.dumps(data, ensure_ascii=False, indent=2)``
    """
    if format == "json":
        console.print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    if isinstance(data, str):
        console.print(data)
        return

    if isinstance(data, dict):
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("Key", style="dim")
        table.add_column("Value")
        for k, v in data.items():
            table.add_row(str(k), _fmt(v))
        console.print(table)
        return

    if isinstance(data, list) and data and isinstance(data[0], dict):
        table = Table(title=title, show_header=True, header_style="bold cyan")
        for col in data[0]:
            table.add_column(str(col))
        for row in data:
            table.add_row(*(_fmt(row.get(c, "")) for c in data[0]))
        console.print(table)
        return

    console.print(str(data))


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value) if value is not None else ""
