#!/usr/bin/env bash
set -euo pipefail

LIMIT="${1:-5}"
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app alerts latest --limit "${LIMIT}"
