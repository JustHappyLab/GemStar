#!/usr/bin/env bash
set -euo pipefail

cd /Users/ken/workspace/GemStar
STATUS_MD="artifacts/current/trade_status.md"
STATUS_JSON="artifacts/current/trade_status.json"

if [[ -f "${STATUS_MD}" ]]; then
  cat "${STATUS_MD}"
elif [[ -f "${STATUS_JSON}" ]]; then
  cat "${STATUS_JSON}"
else
  echo "GemStar has not generated artifacts/current/trade_status.md yet."
  echo "Run: uv run python -m src.cli.app trade --once --max-cycles 1"
fi
