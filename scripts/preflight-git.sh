#!/usr/bin/env bash
set -euo pipefail
uv run ruff check . && uv run pytest -q && gitleaks protect --staged --no-banner
