"""gemstar roles / strategies / factors — list subcommands."""

from __future__ import annotations

from pathlib import Path

import typer

from src.cli.output import get_output_format
from src.cli.output import console, emit


def roles_cmd() -> None:
    """List available roles."""
    from src.roles.registry import RoleRegistry

    fmt = get_output_format()
    registry = RoleRegistry()
    roles = registry.list_roles() if hasattr(registry, "list_roles") else []

    if not roles:
        import yaml
        roles_dir = Path("roles")
        if roles_dir.exists():
            for f in sorted(roles_dir.glob("*.yaml")):
                data = yaml.safe_load(f.read_text()) or {}
                roles.append({
                    "name": data.get("name", f.stem),
                    "provider": data.get("provider", "claude_code"),
                    "skills": ", ".join(data.get("skills", [])),
                    "timeout": data.get("timeout", 120),
                })

    if fmt == "json":
        emit(roles, format="json")
    else:
        emit(roles, format="table", title="Roles")


def strategies_cmd() -> None:
    """List strategy configs."""
    import yaml

    fmt = get_output_format()
    strategies_dir = Path("strategies")
    entries = []
    if strategies_dir.exists():
        for d in sorted(strategies_dir.iterdir()):
            config_file = d / "config.yaml"
            if config_file.exists():
                data = yaml.safe_load(config_file.read_text()) or {}
                entries.append({
                    "name": data.get("name", d.name),
                    "universe": data.get("universe", "auto"),
                    "timer": data.get("timer", {}).get("mode", "?"),
                    "factors": len(data.get("factors", [])),
                    "top_n": data.get("top_n", 5),
                })

    if fmt == "json":
        emit(entries, format="json")
    else:
        emit(entries, format="table", title="Strategies")


def factors_cmd() -> None:
    """Show factor pool."""
    from src.factors.pool import load_pool

    fmt = get_output_format()
    try:
        pool = load_pool()
    except FileNotFoundError:
        console.print("[yellow]No factor pool found. Create factors/pool.json first.[/yellow]")
        return

    entries = []
    for category in ("active", "watchlist", "candidates", "retired"):
        for f in getattr(pool, category, []):
            entries.append({
                "name": f.name,
                "source": f.source,
                "status": category,
                "ic_ir": f"{f.ic_ir:.2f}" if f.ic_ir is not None else "",
                "coverage": f"{f.coverage:.1%}" if f.coverage is not None else "",
            })

    if fmt == "json":
        emit(entries, format="json")
    else:
        emit(entries, format="table", title="Factor Pool")
