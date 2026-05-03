"""gemstar doctor — environment checklist and config validation."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import typer
import yaml

from src.cli.app import get_output_format
from src.cli.config import find_config, load_config
from src.cli.output import console, emit


def _check(name: str, ok: bool, detail: str = "") -> dict:
    """Return a single check result."""
    return {"name": name, "status": "ok" if ok else "fail", "detail": detail}


def _cli_available(cmd: str) -> bool:
    """Check if a CLI tool is on PATH."""
    return shutil.which(cmd) is not None


def _cli_auth_check(cmd: str, args: list[str], env_key: str | None = None) -> tuple[bool, str]:
    """Try running a CLI to verify it's installed and authenticated.

    Returns (ok, detail).
    """
    if not _cli_available(cmd):
        return False, f"{cmd} not found on PATH"

    # For codex, just check OPENAI_API_KEY — no need to spawn codex
    if env_key:
        if not os.environ.get(env_key):
            return False, f"{env_key} not set"
        return True, f"{cmd} available, {env_key} set"

    # For claude/gemini, try a quick --version or --help
    try:
        result = subprocess.run(
            [cmd, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, f"{cmd} available"
        return False, f"{cmd} exited {result.returncode}: {result.stderr.strip()[:200]}"
    except FileNotFoundError:
        return False, f"{cmd} not found"
    except subprocess.TimeoutExpired:
        return False, f"{cmd} timed out"
    except Exception as e:
        return False, f"{cmd} error: {e}"


def doctor_cmd() -> None:
    """Check environment readiness and validate gemstar.yaml."""
    fmt = get_output_format()
    checks: list[dict] = []

    # ── 1. Python version ──────────────────────────────────────
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 13)
    checks.append(_check("Python >= 3.13", py_ok, py_ver))

    # ── 2. uv installed ────────────────────────────────────────
    uv_ok = _cli_available("uv")
    uv_detail = ""
    if uv_ok:
        try:
            r = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=5)
            uv_detail = r.stdout.strip()
        except Exception:
            uv_detail = "found"
    checks.append(_check("uv", uv_ok, uv_detail or "not found"))

    # ── 3. .env file ───────────────────────────────────────────
    env_path = Path(".env")
    env_exists = env_path.exists()
    checks.append(_check(".env", env_exists, str(env_path) if env_exists else "run: cp .env.example .env"))

    # ── 4. TUSHARE_TOKEN ───────────────────────────────────────
    tushare_token = os.environ.get("TUSHARE_TOKEN", "")
    if not tushare_token and env_exists:
        # Try loading from .env manually
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("TUSHARE_TOKEN=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and val != "your_tushare_token_here":
                    tushare_token = val
    ts_ok = bool(tushare_token)
    checks.append(_check("TUSHARE_TOKEN", ts_ok, "set" if ts_ok else "not set in .env or environment"))

    # ── 5. gemstar.yaml ────────────────────────────────────────
    config_path = find_config()
    config_ok = config_path is not None
    config_detail = str(config_path) if config_path else "not found, run: gemstar init"
    checks.append(_check("gemstar.yaml", config_ok, config_detail))

    config = None
    if config_ok:
        try:
            config = load_config(config_path)
            checks.append(_check("gemstar.yaml syntax", True, "valid"))
        except Exception as e:
            checks.append(_check("gemstar.yaml syntax", False, str(e)[:200]))

    # ── 6. state.db ────────────────────────────────────────────
    db_path = config.db_path if config else "state.db"
    db_exists = Path(db_path).exists()
    db_detail = str(db_path) if db_exists else "run: gemstar init"
    checks.append(_check("state.db", db_exists, db_detail))

    # ── 7. roles/*.yaml ────────────────────────────────────────
    roles_dir = Path("roles")
    if roles_dir.exists():
        role_files = sorted(roles_dir.glob("*.yaml"))
        bad_roles = []
        for rf in role_files:
            try:
                data = yaml.safe_load(rf.read_text())
                if not data or "name" not in data:
                    bad_roles.append(rf.name)
            except Exception:
                bad_roles.append(rf.name)
        if bad_roles:
            checks.append(_check("roles/*.yaml", False, f"invalid: {', '.join(bad_roles)}"))
        else:
            checks.append(_check("roles/*.yaml", True, f"{len(role_files)} roles loaded"))
    else:
        checks.append(_check("roles/*.yaml", False, "roles/ directory not found"))

    # ── 8. factors/pool.json ───────────────────────────────────
    pool_path = Path("factors/pool.json")
    if pool_path.exists():
        try:
            json.loads(pool_path.read_text())
            checks.append(_check("factors/pool.json", True, "valid"))
        except Exception as e:
            checks.append(_check("factors/pool.json", False, f"invalid JSON: {e}"))
    else:
        checks.append(_check("factors/pool.json", False, "not found"))

    # ── 9. LLM provider CLIs ───────────────────────────────────
    cli_checks = [
        ("claude CLI", "claude", ["--version"], None),
        ("codex CLI", "codex", ["--version"], None),
        ("gemini CLI", "gemini", ["--version"], None),
    ]
    for label, cmd, args, env_key in cli_checks:
        ok, detail = _cli_auth_check(cmd, args, env_key)
        checks.append(_check(label, ok, detail))

    # ── 10. Data cache directory ────────────────────────────────
    cache_dir = Path(config.data_cache_dir) if config else Path("data/raw")
    cache_exists = cache_dir.exists()
    checks.append(_check("data cache dir", cache_exists, str(cache_dir) if cache_exists else "will be created on fetch"))

    # ── Output ─────────────────────────────────────────────────
    if fmt == "json":
        emit(checks, format="json")
    else:
        console.print("[bold]GemStar Doctor[/bold]\n")
        any_fail = False
        for c in checks:
            icon = "[green]ok[/]" if c["status"] == "ok" else "[red]FAIL[/]"
            detail = f"  [dim]{c['detail']}[/dim]" if c["detail"] else ""
            console.print(f"  {icon}  {c['name']}{detail}")
            if c["status"] == "fail":
                any_fail = True

        console.print()
        if any_fail:
            console.print("[yellow]Some checks failed. Fix the issues above before running the pipeline.[/yellow]")
            raise typer.Exit(1)
        else:
            console.print("[green]All checks passed. Ready to run.[/green]")
