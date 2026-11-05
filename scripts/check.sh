#!/usr/bin/env bash
# Run every automated check: Python lint + tests, frontend types + tests.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
cd frontend
pnpm exec tsc -b
pnpm test
